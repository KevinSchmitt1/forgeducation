"""Environment provisioning — build (or reuse) a venv a lesson can actually run in.

The localLLM run shipped a hollow lesson because its env lacked torch/transformers, so
every substantive cell skipped behind `if HAVE_DEPS:` guards yet reported ok=True (see
docs/architecture/10-output-quality-remediation.md, P0/D1). The fix is to derive the
lesson's environment from the planner's prerequisites (Phase 3) and **provision it for
real** before execution, so cells run instead of skipping.

provision_environment() takes a resolved RequirementSet and:
  1. optionally refuses anything outside a caller-supplied allow-list (off by default),
  2. reuses a content-addressed venv keyed by the requirements hash + interpreter
     version (heavy deps download once, reused across runs — the key cost lever),
  3. otherwise builds the venv, pip-installs under a timeout, enforces a size cap,
     and registers a Jupyter kernel the executor runs against.

Failure is honest: if essential deps cannot be installed the result is ok=False (the
caller writes a failing execution report, caught by the Phase-2 gate), never a
green-but-hollow environment.

Security posture: every external call is a subprocess with an **argument list** (never
a shell string), so package names/specifiers cannot inject commands. The primary control
against installing a *fabricated* package is upstream, in dependencies.py: requirements
come only from the planner's structured block, never mined from prose (doc 18, D4) — that
is what closed the arbitrary-code-execution path. Timeout and size cap bound resource
abuse. There is deliberately no default package allow-list; see the note on
DEFAULT_ALLOWED_PACKAGES for why curating one cost more than it protected. The subprocess
runner and size probe are injectable so the logic is unit-tested with no real venv, pip,
or network.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from forged.pipeline.dependencies import RequirementSet

# ── Tunables / security limits ───────────────────────────────────────────────────

KERNEL_PREFIX = "forged-"
READY_MARKER = ".forged-ready"

DEFAULT_INSTALL_TIMEOUT_SECONDS = 600  # pip install ceiling (heavy wheels like torch)
DEFAULT_VENV_TIMEOUT_SECONDS = 120
DEFAULT_MAX_ENV_SIZE_MB = 4096  # torch ~2 GB; leave headroom but cap runaway installs

# NOT a default policy any more — kept as a convenience set a caller may opt into via
# `provision_environment(..., allowed_packages=...)`, and used by the tests.
#
# Why the default gate was removed (2026-07-30): its real job was stopping *fabricated*
# package names from reaching `pip install`, which is a genuine arbitrary-code-execution
# vector — the planner once emitted `not`, `required`, `for`, `the`, `core`, four of which
# are live PyPI packages whose `setup.py` would have run. That vector was closed at the
# source when doc 18's D4 deleted the prose miner: requirements can now only come from the
# planner's structured block, so a fabricated name cannot get here at all.
#
# What remained was a hand-curated list vetoing packages the planner *deliberately chose*,
# and it could not keep up. It killed paid modules on `openai`, `faiss-cpu`, `pytest`,
# then — one day after being widened for those — on `pydantic`, `jinja2`, `structlog`,
# `prometheus-client`, `respx` and `jsonschema`. Every miss costs a real paid build, and
# no curator anticipates every topic a learner might ask about. Refusing what the planner
# asked for is not safety here; it is a guaranteed recurring outage.
#
# Remaining guards are the ones that need no curation: the install timeout and the
# environment size cap above.
DEFAULT_ALLOWED_PACKAGES: frozenset[str] = frozenset(
    {
        # core scientific / data
        "numpy", "pandas", "scipy", "matplotlib", "seaborn", "sympy", "statsmodels",
        "scikit-learn", "scikit-image", "pillow", "networkx",
        # ml / dl
        "torch", "torchvision", "torchaudio", "tensorflow", "keras", "jax", "jaxlib",
        "transformers", "datasets", "accelerate", "tokenizers", "huggingface-hub",
        "sentencepiece", "safetensors", "evaluate", "xgboost", "lightgbm",
        # parameter-efficient / supervised fine-tuning (LoRA etc.) — first-party HF
        "peft", "trl", "sentence-transformers",
        # notebooks / viz / utils
        "ipykernel", "ipython", "ipywidgets", "tqdm", "plotly", "altair",
        "requests", "beautifulsoup4", "lxml", "pyyaml", "rich", "tabulate",
        "openpyxl", "polars", "pyarrow", "nltk", "spacy", "gensim",
        # agent / LLM stack (doc 18, D5 — absent entirely, killed module 1's
        # openai/faiss-cpu/pytest provisioning)
        "openai", "anthropic", "faiss-cpu", "langchain", "langchain-core",
        "langchain-community", "langgraph", "chromadb", "tiktoken", "pytest",
        "python-dotenv", "gitpython", "httpx",
    }
)


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of a provisioning attempt.

    ok: True when the lesson can run (a kernel is ready, or no deps were needed).
    kernel_name: the Jupyter kernel to execute against; None means "use the base
        kernel" (an empty requirement set needs no venv).
    cache_hit: True when an existing content-addressed venv was reused.
    installed: the rendered requirement lines that define the env.
    rejected: requirement names refused by a caller-supplied allow-list (empty by
        default, since no allow-list is imposed).
    error: human-readable failure cause when ok is False; None on success.
    """

    ok: bool
    requirements_hash: str
    kernel_name: str | None
    cache_hit: bool = False
    installed: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    error: str | None = None


# Injectable subprocess seam: same shape as subprocess.run for an argv list.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _venv_python(venv_dir: Path) -> Path:
    """Path to the venv's interpreter (POSIX `bin/`, Windows `Scripts/`)."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _dir_size_mb(path: Path) -> float:
    """Total size of a directory tree in MB (follows no symlinks)."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink():
            total += p.stat().st_size
    return total / (1024 * 1024)


def _cache_key(requirements_hash: str) -> str:
    """Content-addressed key: requirements + interpreter version (cache invalidates
    when either changes, per the risk table's stale-env mitigation)."""
    py = f"py{sys.version_info.major}.{sys.version_info.minor}"
    return f"{requirements_hash[:16]}-{py}"


def provision_environment(
    requirement_set: RequirementSet,
    *,
    cache_root: Path,
    python_executable: str | None = None,
    allowed_packages: frozenset[str] | None = None,
    install_timeout_seconds: int = DEFAULT_INSTALL_TIMEOUT_SECONDS,
    venv_timeout_seconds: int = DEFAULT_VENV_TIMEOUT_SECONDS,
    max_env_size_mb: int = DEFAULT_MAX_ENV_SIZE_MB,
    runner: Runner = subprocess.run,
    size_probe: Callable[[Path], float] = _dir_size_mb,
) -> ProvisionResult:
    """Build or reuse a venv for a lesson's requirements and return a kernel to run in.

    Args:
        requirement_set: the lesson's resolved dependencies (from Phase 3).
        cache_root: directory holding content-addressed venvs (shared across runs).
        python_executable: interpreter used to create the venv (defaults to the
            running interpreter).
        allowed_packages: optional policy. None (the default) installs whatever the
            plan asked for; a set restricts to those PEP 503-normalized names.
        install_timeout_seconds / venv_timeout_seconds: subprocess ceilings.
        max_env_size_mb: reject an installed env larger than this.
        runner / size_probe: injectable seams for testing.

    Returns:
        A ProvisionResult. ok=False carries an explanation and never leaves a usable
        cache entry behind, so a failed build is rebuilt (or re-fails) next time.
    """
    python_executable = python_executable or sys.executable
    # No curated allow-list by default: `allowed_packages=None` means "install what the
    # plan asked for". See the note on DEFAULT_ALLOWED_PACKAGES for why the default gate
    # was removed. A caller that genuinely wants a policy can still pass a set.
    allowed = allowed_packages
    rhash = requirement_set.requirements_hash
    reqs = requirement_set.requirements

    # A malformed requirements block (doc 18, D4/D6) must fail honestly and loudly —
    # never silently treated as "no dependencies needed" (it has no requirements
    # either, so it would otherwise fall into the empty-set branch below) and never
    # phrased as a policy/allow-list violation, which is what hid a parser bug behind
    # a security-sounding message for two days.
    if requirement_set.source == "malformed":
        return ProvisionResult(
            ok=False,
            requirements_hash=rhash,
            kernel_name=None,
            error=requirement_set.error or "The plan's requirements block is malformed.",
        )

    # No third-party deps → nothing to build; run on the base kernel.
    if not reqs:
        return ProvisionResult(ok=True, requirements_hash=rhash, kernel_name=None)

    # Optional policy gate: only when a caller explicitly supplied an allow-list.
    rejected = () if allowed is None else tuple(r.name for r in reqs if r.name not in allowed)
    if rejected:
        return ProvisionResult(
            ok=False,
            requirements_hash=rhash,
            kernel_name=None,
            rejected=rejected,
            error=(
                "Refusing to provision: package(s) outside the allow-list: "
                f"{', '.join(rejected)}. Extend DEFAULT_ALLOWED_PACKAGES intentionally."
            ),
        )

    key = _cache_key(rhash)
    kernel_name = f"{KERNEL_PREFIX}{key}"
    venv_dir = cache_root / key
    rendered = tuple(r.render() for r in sorted(reqs, key=lambda r: r.name))

    # Cache hit: a previous run already built this exact environment.
    if (venv_dir / READY_MARKER).exists():
        return ProvisionResult(
            ok=True,
            requirements_hash=rhash,
            kernel_name=kernel_name,
            cache_hit=True,
            installed=rendered,
        )

    return _build_environment(
        venv_dir=venv_dir,
        kernel_name=kernel_name,
        requirements_hash=rhash,
        rendered=rendered,
        python_executable=python_executable,
        install_timeout_seconds=install_timeout_seconds,
        venv_timeout_seconds=venv_timeout_seconds,
        max_env_size_mb=max_env_size_mb,
        runner=runner,
        size_probe=size_probe,
    )


def _requirement_name(requirement: str) -> str:
    """The bare package name from a requirement string ('matplotlib>=3.5' -> 'matplotlib')."""
    return re.split(r"[<>=!~;\[\s]", requirement.strip(), maxsplit=1)[0].lower()


def _warm_up_matplotlib(
    venv_py: str, rendered: tuple[str, ...], runner: Runner, timeout_seconds: int
) -> None:
    """Best-effort: pre-build matplotlib's font cache in the fresh venv (headless), so
    the notebook's first `import matplotlib.pyplot` is warm and fast. No-op when the
    lesson doesn't use matplotlib. Never fails provisioning — a failed warm-up just
    means the first notebook import pays the cost (as it did before this existed)."""
    if not any(_requirement_name(r) == "matplotlib" for r in rendered):
        return
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        runner(
            [venv_py, "-c", "import matplotlib.pyplot"],
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            env={**os.environ, "MPLBACKEND": "Agg"},
        )


def _build_environment(
    *,
    venv_dir: Path,
    kernel_name: str,
    requirements_hash: str,
    rendered: tuple[str, ...],
    python_executable: str,
    install_timeout_seconds: int,
    venv_timeout_seconds: int,
    max_env_size_mb: int,
    runner: Runner,
    size_probe: Callable[[Path], float],
) -> ProvisionResult:
    """Create the venv, install deps, enforce the size cap, and register the kernel.

    Any failure removes the half-built venv so it is never reused as a cache hit, and
    returns ok=False with the cause. Keeps the happy path linear with early returns."""

    def fail(error: str) -> ProvisionResult:
        shutil.rmtree(venv_dir, ignore_errors=True)
        return ProvisionResult(
            ok=False, requirements_hash=requirements_hash, kernel_name=None, error=error
        )

    # Fresh start: never install on top of a previous partial build.
    shutil.rmtree(venv_dir, ignore_errors=True)
    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        create = runner(
            [python_executable, "-m", "venv", str(venv_dir)],
            timeout=venv_timeout_seconds,
            capture_output=True,
            text=True,
        )
        if create.returncode != 0:
            return fail(f"Could not create venv: {create.stderr.strip() or 'unknown error'}")

        venv_py = str(_venv_python(venv_dir))
        # Install the lesson deps + ipykernel (so the venv can back a Jupyter kernel).
        # --no-input: never block on an interactive prompt inside the timeout window.
        install = runner(
            [venv_py, "-m", "pip", "install", "--no-input", "ipykernel", *rendered],
            timeout=install_timeout_seconds,
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            return fail(
                "Failed to install required packages "
                f"({', '.join(rendered)}): {install.stderr.strip() or 'pip error'}"
            )

        size_mb = size_probe(venv_dir)
        if size_mb > max_env_size_mb:
            return fail(
                f"Provisioned environment exceeds the size cap: {size_mb:.0f} MB > "
                f"{max_env_size_mb} MB."
            )

        register = runner(
            [venv_py, "-m", "ipykernel", "install", "--user", "--name", kernel_name],
            timeout=venv_timeout_seconds,
            capture_output=True,
            text=True,
        )
        if register.returncode != 0:
            return fail(f"Could not register kernel: {register.stderr.strip() or 'unknown error'}")

        # Build matplotlib's font cache now — once, and outside the executor's per-cell
        # timeout. A cold `import matplotlib.pyplot` builds it (~60-90s on macOS with
        # many fonts); left to the notebook, that import exceeds the 120s cell timeout
        # and kills the whole run at iteration 0 (observed on real smoke runs).
        _warm_up_matplotlib(venv_py, rendered, runner, install_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return fail(f"Provisioning timed out after {exc.timeout}s.")
    except OSError as exc:
        return fail(f"Provisioning failed: {exc}")

    # Mark ready only after every step succeeded — the marker is the cache validity flag.
    (venv_dir / READY_MARKER).write_text("\n".join(rendered) + "\n", encoding="utf-8")
    return ProvisionResult(
        ok=True,
        requirements_hash=requirements_hash,
        kernel_name=kernel_name,
        cache_hit=False,
        installed=rendered,
    )
