"""Deterministic lesson-mode extraction from a lesson plan.

Not every technical topic is compute-and-show Python. "Working with agentic AI"
teaches artifacts — agent definitions, persona ``.md`` files, framework wiring, a
loop harness, a project file tree — which are *built and validated*, not run to
print a number. The planner infers which kind of lesson a topic needs and declares
it as a machine-readable tag; this module turns that tag into a ``LessonMode`` so
the deterministic gate (``structure.py``) and classifier (``failure.py``) can treat
an artifact lesson on its own terms without ever faking execution.

Design of record: docs/architecture/17-lesson-modes.md.

Three modes, in ascending distance from "runs and shows a result":

  * ``executable`` — the default and the historical behavior. Cells compute and
    demonstrate; the learner sees output. Full existing rigor applies.
  * ``artifact`` — the deliverable is a file/config/scaffold. Cells *write* the
    artifact and *validate* it (parse / structure / lint / mocked dry-run), so the
    self-check survives — only its target changes.
  * ``conceptual`` — a rare fallback: prose and diagrams, nothing runs. The run
    summary says so loudly rather than implying a check that never happened.

extract_lesson_mode() reads the planner's ``lesson-mode`` fenced block, mirroring
the ``requirements`` block that dependencies.py already parses. Conservative by
design: anything absent, ambiguous, or unrecognized falls back to ``executable``,
never the other way — rigor is never silently dropped from a topic that earned it.

Dependency: stdlib only (re, typing). No imports from other pipeline modules,
mirroring structure.py/dependencies.py so there is never an import cycle.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

# ── Contract ─────────────────────────────────────────────────────────────────────

LessonMode = Literal["executable", "artifact", "conceptual"]

# The conservative default. A plan that declares nothing, or declares a word we do
# not recognize, is treated as fully executable so the existing anti-hollow rigor
# applies. We only leave this default on an explicit, recognized declaration.
DEFAULT_MODE: LessonMode = "executable"

_VALID_MODES: frozenset[str] = frozenset(get_args(LessonMode))

# The structured contract: a fenced block tagged `lesson-mode`, mirroring the
# `requirements` block in dependencies.py. Non-greedy body so only the first block
# is taken; case-insensitive tag for robustness against `Lesson-Mode` etc.
_FENCE_RE = re.compile(r"```lesson-mode[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


# ── Extraction ───────────────────────────────────────────────────────────────────


def extract_lesson_mode(plan_text: str) -> LessonMode:
    """Return the lesson mode the planner declared, or the conservative default.

    Args:
        plan_text: the raw lesson-plan markdown emitted by the planner.

    Returns:
        The declared ``LessonMode`` when the first ``lesson-mode`` fenced block
        names a recognized mode (case-insensitively). Otherwise ``DEFAULT_MODE``
        (``"executable"``) — including when ``plan_text`` is empty, has no such
        block, or names an unknown word.
    """
    if not plan_text:
        return DEFAULT_MODE

    match = _FENCE_RE.search(plan_text)
    if match is None:
        return DEFAULT_MODE

    # First non-empty line of the block, normalized. Guards against surrounding
    # blank lines or an accidental trailing comment on its own line.
    for line in match.group(1).splitlines():
        candidate = line.strip().lower()
        if not candidate:
            continue
        if candidate in _VALID_MODES:
            # candidate is a validated member of LessonMode's literals.
            return candidate  # type: ignore[return-value]
        # A non-empty but unrecognized first token means the planner tried to
        # declare something we do not support — stay conservative, do not guess.
        return DEFAULT_MODE

    return DEFAULT_MODE


def render_mode_directive(mode: LessonMode | None) -> str:
    """The hand-down text telling the lesson planner a mode was already decided.

    A mode chosen upstream — by the course planner, or by the operator at the plan gate
    — is binding: the lesson planner must plan within it rather than re-inferring and
    drifting back to `executable` (doc 18, D2/D3). `None` means undecided and renders
    nothing, leaving the planner's own inference untouched.

    Shared by both seeding paths (the course orchestrator's `_seed_module_store` and the
    single-lesson `learn` branch in the CLI) so the two cannot drift apart.
    """
    if mode is None:
        return ""
    return (
        "\n\n### Lesson mode (already decided — binding)\n"
        f"This lesson's mode is `{mode}`. Plan within it; do not re-infer it.\n"
    )
