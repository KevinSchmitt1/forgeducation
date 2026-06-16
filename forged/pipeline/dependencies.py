"""Deterministic dependency extraction from a lesson plan.

The planner declares the lesson's environment in its ``## Prerequisites`` section.
Today that list is only inlined into a setup-check cell; nothing materializes it as
a real dependency manifest or uses it to provision the kernel — which is how the
localLLM run shipped a lesson whose payload sat behind ``if HAVE_DEPS:`` guards and
silently skipped (see docs/architecture/10-output-quality-remediation.md, P6/P0).

extract_requirements() turns the plan into a normalized requirement set plus a stable
content-addressed hash, with no LLM and no network. Two sources, in priority order:

  1. A fenced ```requirements block the planner now emits — the machine-readable
     contract. Parsed verbatim; must be pip-installable.
  2. Regex-on-prose fallback for older plans: scan ``pip install ...`` lines.

The requirements hash is the key Phase 5's content-addressed venv/wheel cache will use,
so heavy deps are downloaded once and reused. It is computed over the requirement
*content only* (sorted, normalized) so it is reproducible and offline-testable; Phase 5
combines it with the interpreter version when forming the actual cache key.

Dependency: stdlib only (re, hashlib, dataclasses). No imports from other pipeline
modules, mirroring structure.py so there is never an import cycle.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# ── Patterns ─────────────────────────────────────────────────────────────────────

# The structured contract: a fenced block tagged `requirements`. Non-greedy body so
# only the first block is taken; case-insensitive tag for robustness.
_FENCE_RE = re.compile(r"```requirements[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# pip-install invocations in prose: `pip install ...`, `pip3 install ...`,
# `python -m pip install ...`. Captures the remainder of the line (the packages).
_PIP_INSTALL_RE = re.compile(
    r"(?:python\s+-m\s+)?pip[0-9]*\s+install\s+(?P<args>[^\n]+)",
    re.IGNORECASE,
)

# Prose contains decoy "pip install ..." phrases ("then pip install the HF packages
# above."). A real install command leads with a package name; an English clause leads
# with an article/verb. When the first token after `pip install` is one of these
# function words, the match is prose, not a command — skip it rather than mine the
# sentence for fake packages. Conservative by design: the structured block is the
# trustworthy path, so a missed legacy dep beats a fabricated one.
_PROSE_LEAD_WORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "then", "above", "below", "following",
        "package", "packages", "using", "use", "via", "with", "from", "for",
        "your", "you", "these", "those", "this", "that", "all", "any", "official",
        "instructions", "them", "it",
    }
)

# One requirement token: a PEP 503-ish name, optional [extras], optional version
# specifier(s). Anything past a `#`/`;` (comment / environment marker) is ignored.
_REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[^\]]+\])?"
    r"(?P<spec>(?:[<>=!~]=?|===)[^\s;#]*)?$"
)


# ── Value objects ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Requirement:
    """One pip-installable dependency: a normalized name + an optional specifier.

    ``name`` is PEP 503-normalized (lowercase, ``-`` separators). ``specifier`` is the
    rendered tail appended verbatim to the name in requirements.txt — it may carry
    extras and/or version constraints (e.g. ``[standard]>=0.20``, ``>=2.0,<3.0``) and
    is empty for an unpinned package.
    """

    name: str
    specifier: str = ""

    def render(self) -> str:
        return f"{self.name}{self.specifier}"


@dataclass(frozen=True)
class RequirementSet:
    """The lesson's resolved dependencies plus how they were found.

    ``source`` records provenance for the audit trail: ``"structured"`` (the planner's
    fenced block, even if empty), ``"prose"`` (regex fallback), or ``"none"`` (nothing
    declared). The requirements tuple preserves first-seen order; rendering and hashing
    sort by name so neither depends on declaration order.
    """

    requirements: tuple[Requirement, ...]
    source: str

    @property
    def requirements_hash(self) -> str:
        """Stable sha256 over the sorted, normalized requirement lines (hex digest).

        Content-addressed: two plans that declare the same packages — in any order,
        via any source — hash identically. The empty set has a fixed digest too.
        """
        payload = "\n".join(sorted(r.render() for r in self.requirements))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def requirement_for(self, name: str) -> Requirement:
        """Look up a requirement by (un-normalized) name. Raises if absent."""
        target = normalize_name(name)
        for req in self.requirements:
            if req.name == target:
                return req
        names = sorted(r.name for r in self.requirements)
        raise KeyError(f"No requirement named {name!r} in {names}")

    def render_txt(self) -> str:
        """Render pip-parseable requirements.txt content (sorted, header-commented)."""
        header = "# Auto-generated from the lesson plan — see README.md.\n"
        if not self.requirements:
            return header + "# This lesson needs no third-party packages.\n"
        body = "\n".join(r.render() for r in sorted(self.requirements, key=lambda r: r.name))
        return header + body + "\n"


# ── Parsing helpers ───────────────────────────────────────────────────────────────


def normalize_name(raw: str) -> str:
    """PEP 503 normalization: lowercase, collapse runs of ``-_.`` to a single ``-``."""
    return re.sub(r"[-_.]+", "-", raw.strip().lower())


def _parse_token(token: str) -> Requirement | None:
    """Parse one requirement token (e.g. ``torch>=2.0``) into a Requirement, or None.

    Returns None for flags (``--upgrade``), options, URLs, and anything that is not a
    plain ``name[extras][specifier]`` token, so prose noise is dropped, not guessed at.
    """
    token = token.strip().strip(",")
    if not token or token.startswith("-"):
        return None
    match = _REQUIREMENT_RE.match(token)
    if match is None:
        return None
    extras = match.group("extras") or ""
    spec = match.group("spec") or ""
    return Requirement(name=normalize_name(match.group("name")), specifier=f"{extras}{spec}")


def _dedupe(requirements: list[Requirement]) -> tuple[Requirement, ...]:
    """Collapse duplicate names (first-seen order), preferring a specifier-bearing entry."""
    by_name: dict[str, Requirement] = {}
    for req in requirements:
        existing = by_name.get(req.name)
        if existing is None or (not existing.specifier and req.specifier):
            by_name[req.name] = req
    return tuple(by_name.values())


def _parse_block(body: str) -> list[Requirement]:
    """Parse the lines of a structured requirements block, skipping blanks/comments."""
    parsed: list[Requirement] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        req = _parse_token(stripped)
        if req is not None:
            parsed.append(req)
    return parsed


def _parse_prose(plan_markdown: str) -> list[Requirement]:
    """Scan every ``pip install ...`` line for package tokens, skipping prose decoys."""
    parsed: list[Requirement] = []
    for match in _PIP_INSTALL_RE.finditer(plan_markdown):
        tokens = [_parse_token(t) for t in match.group("args").split()]
        candidates = [req for req in tokens if req is not None]
        if not candidates or candidates[0].name in _PROSE_LEAD_WORDS:
            # Leads with an article/verb (or nothing parseable) → an English clause,
            # not an install command. Don't fabricate packages from a sentence.
            continue
        parsed.extend(candidates)
    return parsed


# ── Public entry point ─────────────────────────────────────────────────────────────


def extract_requirements(plan_markdown: str) -> RequirementSet:
    """Extract the lesson's dependencies from its plan markdown.

    Args:
        plan_markdown: the planner's lesson plan (its ``## Prerequisites`` section is
            where dependencies live, but the whole document is scanned).

    Returns:
        A RequirementSet. The structured ```requirements block wins when present (even
        if empty — an explicit "no deps" is authoritative); otherwise the prose pip
        fallback is used; otherwise an empty set with source ``"none"``.
    """
    fence = _FENCE_RE.search(plan_markdown)
    if fence is not None:
        return RequirementSet(_dedupe(_parse_block(fence.group(1))), source="structured")

    prose = _parse_prose(plan_markdown)
    if prose:
        return RequirementSet(_dedupe(prose), source="prose")

    return RequirementSet((), source="none")
