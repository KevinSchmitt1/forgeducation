"""Unit tests for environment provisioning (Phase 5).

provision_environment() builds (or reuses) a per-run venv from a lesson's resolved
requirements, keyed by the content-addressed requirements hash, then registers a
Jupyter kernel the executor runs against — so a lesson's cells run for real instead
of skipping behind `if HAVE_DEPS:` guards.

These tests inject a fake subprocess `runner` (and a `size_probe`): no real venv, no
network, no pip. They assert the security guards (allow-list, install timeout, size
cap), the content-addressed cache (hit vs miss), and that failures are reported
honestly (ok=False) rather than degrading to a usable-looking environment.

Run with:
    pytest tests/test_provisioning.py -v
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forged.pipeline.dependencies import RequirementSet, extract_requirements
from forged.provisioning import (
    KERNEL_PREFIX,
    ProvisionResult,
    _dir_size_mb,
    provision_environment,
)

# ── Fakes ───────────────────────────────────────────────────────────────────────


def _reqs(*lines: str) -> RequirementSet:
    block = "```requirements\n" + "\n".join(lines) + "\n```\n"
    return extract_requirements(block)


class FakeRunner:
    """Records subprocess calls and simulates success, creating dirs as `python -m
    venv` would. Configurable to fail a specific command substring."""

    def __init__(self, fail_on: str | None = None, timeout_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on
        self.timeout_on = timeout_on

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        if self.timeout_on and self.timeout_on in joined:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))
        # Simulate `python -m venv <dir>` creating the venv directory tree.
        if "venv" in cmd:
            venv_dir = Path(cmd[-1])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            (venv_dir / "bin" / "python").write_text("#!stub", encoding="utf-8")
        if self.fail_on and self.fail_on in joined:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")


def _provision(req_set, cache_root, **kw):
    """Call provision_environment with test-friendly defaults."""
    kw.setdefault("runner", FakeRunner())
    kw.setdefault("size_probe", lambda _p: 10.0)
    kw.setdefault("allowed_packages", frozenset({"numpy", "pandas", "matplotlib"}))
    return provision_environment(req_set, cache_root=cache_root, **kw)


# ── No dependencies → base kernel, no venv ───────────────────────────────────────


def test_empty_requirements_uses_base_kernel_without_provisioning(tmp_path):
    runner = FakeRunner()
    result = _provision(_reqs(), tmp_path / "cache", runner=runner)
    assert result.ok is True
    assert result.kernel_name is None  # signals "run on the base kernel"
    assert result.cache_hit is False
    assert runner.calls == []  # nothing was built


# ── Allow-list (security) ────────────────────────────────────────────────────────


def test_package_outside_allow_list_is_refused_without_installing(tmp_path):
    runner = FakeRunner()
    result = _provision(_reqs("numpy>=1.26", "evil-pkg"), tmp_path / "cache", runner=runner)
    assert result.ok is False
    assert "evil-pkg" in result.rejected
    assert result.error is not None
    assert runner.calls == []  # refused before any subprocess ran


# ── Cache miss → build, install, register kernel ────────────────────────────────


def test_cache_miss_builds_venv_installs_and_registers_kernel(tmp_path):
    cache = tmp_path / "cache"
    runner = FakeRunner()
    result = _provision(_reqs("numpy>=1.26", "pandas"), cache, runner=runner)

    assert result.ok is True
    assert result.cache_hit is False
    assert result.kernel_name and result.kernel_name.startswith(KERNEL_PREFIX)
    assert set(result.installed) == {"numpy>=1.26", "pandas"}
    joined = [" ".join(c) for c in runner.calls]
    assert any("-m venv" in c for c in joined)
    assert any("pip install" in c and "numpy>=1.26" in c for c in joined)
    assert any("ipykernel install" in c for c in joined)


def test_cache_hit_skips_rebuild(tmp_path):
    cache = tmp_path / "cache"
    req = _reqs("numpy>=1.26")
    first = _provision(req, cache)
    assert first.ok and not first.cache_hit

    runner2 = FakeRunner()
    second = _provision(req, cache, runner=runner2)
    assert second.ok is True
    assert second.cache_hit is True
    assert second.kernel_name == first.kernel_name
    # No venv build / pip install on a cache hit (kernel re-register is allowed).
    joined = [" ".join(c) for c in runner2.calls]
    assert not any("-m venv" in c for c in joined)
    assert not any("pip install" in c for c in joined)


def test_same_requirements_in_any_order_share_a_cache_key(tmp_path):
    cache = tmp_path / "cache"
    a = _provision(_reqs("numpy>=1.26", "pandas"), cache)
    b = _provision(_reqs("pandas", "numpy>=1.26"), cache, runner=FakeRunner())
    assert b.cache_hit is True
    assert a.kernel_name == b.kernel_name


# ── Honest failures ──────────────────────────────────────────────────────────────


def test_install_failure_reports_not_ok_and_does_not_cache(tmp_path):
    cache = tmp_path / "cache"
    runner = FakeRunner(fail_on="pip install")
    result = _provision(_reqs("numpy>=1.26"), cache, runner=runner)
    assert result.ok is False
    assert result.error is not None
    # A failed build must not be reusable as a cache hit.
    second = _provision(_reqs("numpy>=1.26"), cache, runner=FakeRunner())
    assert second.cache_hit is False


def test_install_timeout_reports_not_ok(tmp_path):
    runner = FakeRunner(timeout_on="pip install")
    result = _provision(_reqs("numpy>=1.26"), tmp_path / "cache", runner=runner)
    assert result.ok is False
    assert result.error is not None and "timed out" in result.error.lower()


def test_env_over_size_cap_is_rejected(tmp_path):
    cache = tmp_path / "cache"
    result = _provision(
        _reqs("numpy>=1.26"), cache, runner=FakeRunner(), size_probe=lambda _p: 9999.0,
        max_env_size_mb=100,
    )
    assert result.ok is False
    assert result.error is not None and "size" in result.error.lower()
    # Oversized env must not be left behind as a cache hit.
    second = _provision(_reqs("numpy>=1.26"), cache, runner=FakeRunner())
    assert second.cache_hit is False


def test_venv_creation_failure_reports_not_ok(tmp_path):
    runner = FakeRunner(fail_on="-m venv")
    result = _provision(_reqs("numpy>=1.26"), tmp_path / "cache", runner=runner)
    assert result.ok is False
    assert result.error is not None and "venv" in result.error.lower()


def test_kernel_registration_failure_reports_not_ok(tmp_path):
    runner = FakeRunner(fail_on="ipykernel install")
    result = _provision(_reqs("numpy>=1.26"), tmp_path / "cache", runner=runner)
    assert result.ok is False
    assert result.error is not None and "kernel" in result.error.lower()


def test_os_error_during_build_is_reported(tmp_path):
    def runner(cmd, **kwargs):
        raise OSError("disk full")

    result = _provision(_reqs("numpy>=1.26"), tmp_path / "cache", runner=runner)
    assert result.ok is False
    assert result.error is not None


# ── Helpers ──────────────────────────────────────────────────────────────────────


def test_dir_size_mb_sums_file_sizes(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"y" * (1 * 1024 * 1024))  # 1 MB
    assert _dir_size_mb(tmp_path) == pytest.approx(3.0, abs=0.01)


# ── Result shape ─────────────────────────────────────────────────────────────────


def test_result_is_frozen():
    r = ProvisionResult(ok=True, requirements_hash="abc", kernel_name=None)
    with pytest.raises((AttributeError, TypeError)):
        r.ok = False  # type: ignore[misc]
