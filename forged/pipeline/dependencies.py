"""Deterministic dependency extraction from a lesson plan.

The planner declares the lesson's environment in its ``## Prerequisites`` section.
Today that list is only inlined into a setup-check cell; nothing materializes it as
a real dependency manifest or uses it to provision the kernel — which is how the
localLLM run shipped a lesson whose payload sat behind ``if HAVE_DEPS:`` guards and
silently skipped (see docs/architecture/10-output-quality-remediation.md, P6/P0).

extract_requirements() turns the plan into a normalized requirement set plus a stable
content-addressed hash, with no LLM and no network. Two structured sources, checked in
priority order, both machine-readable and both trusted:

  1. A fenced ```requirements block — the planner's preferred, unambiguous contract.
  2. An unfenced ``requirements`` heading (bare, or ``## requirements``) on its own
     line, followed by requirement-shaped lines and terminated by a blank line or the
     next markdown heading. The planner emits this format sporadically even though it
     fences other blocks correctly in the same document (see
     docs/architecture/18-mode-selection-bias-and-run-honesty.md, E4) — so this parser
     tolerates the format instead of relying on persona instruction alone.

There is deliberately no third, prose-mining source anymore. An earlier ``pip
install ...`` regex fallback was the sole source of fabricated package names: it once
matched a decoy sentence near a genuine (but unfenced, therefore unread) requirements
block and turned English function words — several of which are real, live, installable
PyPI packages — into "dependencies" to install. A missing dependency should fail
loudly; a fabricated one fails confusingly and dangerously. See doc 18, D4.

A structured block (fenced or heading) that contains content but yields zero
parseable requirements is reported as ``source="malformed"`` with a human-readable
``error`` — never silently treated as "no dependencies needed" and never phrased as an
allow-list/policy violation (that conflation is exactly what hid the parser bug behind
a security-sounding message in doc 18's E4).

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

# The secondary structured contract: a bare `requirements` line (optionally prefixed
# with up to 6 `#`s, i.e. a markdown heading), alone on its own line. Whitespace-only
# padding is tolerated; anything else on the line disqualifies it (it's prose, not a
# block marker).
_HEADING_RE = re.compile(r"^[ \t]*#{0,6}[ \t]*requirements[ \t]*$", re.IGNORECASE | re.MULTILINE)

# What ends an unfenced requirements block: a markdown *section* heading, i.e. two or more
# hashes, which is how the planner writes its plan sections (`## Learning objectives`). A
# single `#` is a requirements.txt comment and must NOT terminate the block — see
# `_unfenced_heading_lines`.
_SECTION_HEADING_RE = re.compile(r"^[ \t]*#{2,6}[ \t]+\S")

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

    ``source`` records provenance for the audit trail:

    - ``"structured"`` — a fenced or unfenced heading block, parsed successfully. This
      includes a deliberately empty block (an explicit "no deps" is authoritative).
    - ``"malformed"`` — a structured block was found and had content, but none of its
      lines parsed as an installable requirement. ``error`` explains why; the caller
      must treat this as a parser failure, never as "no dependencies" and never as a
      policy/allow-list violation.
    - ``"none"`` — no requirements block of either shape was found anywhere.

    The requirements tuple preserves first-seen order; rendering and hashing sort by
    name so neither depends on declaration order.
    """

    requirements: tuple[Requirement, ...]
    source: str
    error: str | None = None

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


def _parse_body(body_lines: list[str]) -> tuple[list[Requirement], bool]:
    """Parse requirement-shaped lines, skipping blanks/comments.

    Returns ``(parsed, had_content)``. ``had_content`` is True when at least one
    non-blank, non-comment line was present, regardless of whether it parsed — it is
    how the caller distinguishes an explicit "no packages" block (no content at all)
    from a malformed one (content present, nothing usable came out of it).
    """
    parsed: list[Requirement] = []
    had_content = False
    for line in body_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        had_content = True
        req = _parse_token(stripped)
        if req is not None:
            parsed.append(req)
    return parsed, had_content


def _unfenced_heading_lines(plan_markdown: str) -> list[str] | None:
    """Body lines of an unfenced ``requirements`` heading block, or None if absent.

    The block starts on the line after the heading and runs until the first blank
    line or the next markdown *section* heading, whichever comes first — deliberately
    narrow so unrelated prose elsewhere in the plan is never swept in.

    A section heading means two or more hashes (`## Learning objectives`), matching how
    the planner actually writes its plans. A single-hash line is a requirements.txt-style
    comment (`# core forecasting lib`) and is passed through to `_parse_body`, which skips
    it — terminating there instead would silently drop every package below the comment,
    with no error and no `malformed` flag.
    """
    match = _HEADING_RE.search(plan_markdown)
    if match is None:
        return None
    # `split("\n")` (not splitlines()) so index 0 is always the (empty) remainder of
    # the heading line itself; real content starts at index 1.
    rest = plan_markdown[match.end() :].split("\n")[1:]
    lines: list[str] = []
    for line in rest:
        if not line.strip() or _SECTION_HEADING_RE.match(line):
            break
        lines.append(line)
    return lines


def _malformed(kind: str) -> RequirementSet:
    return RequirementSet(
        (),
        source="malformed",
        error=(
            f"The plan's {kind} is malformed: none of its lines could be parsed as "
            "installable package requirements. This is a plan-formatting problem — "
            "fix the plan's requirements block."
        ),
    )


# ── Public entry point ─────────────────────────────────────────────────────────────


def extract_requirements(plan_markdown: str) -> RequirementSet:
    """Extract the lesson's dependencies from its plan markdown.

    Args:
        plan_markdown: the planner's lesson plan (its ``## Prerequisites`` section is
            where dependencies live, but the whole document is scanned).

    Returns:
        A RequirementSet. The fenced ```requirements block wins when present;
        otherwise an unfenced ``requirements`` heading block is used; otherwise an
        empty set with source ``"none"``. Either structured source reports
        ``source="malformed"`` instead of an empty/"none" result when it has content
        that yields no usable requirements.
    """
    fence = _FENCE_RE.search(plan_markdown)
    if fence is not None:
        body_lines = fence.group(1).splitlines()
        kind = "fenced requirements block"
    else:
        heading_lines = _unfenced_heading_lines(plan_markdown)
        if heading_lines is None:
            return RequirementSet((), source="none")
        body_lines = heading_lines
        kind = "requirements heading block"

    parsed, had_content = _parse_body(body_lines)
    if had_content and not parsed:
        return _malformed(kind)
    return RequirementSet(_dedupe(parsed), source="structured")
