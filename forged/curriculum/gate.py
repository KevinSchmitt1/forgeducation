"""The interactive plan gate for the smart front door (doc 16, Phase 4).

`forged learn` always shows the proposed plan plus a rough cost/time estimate and runs
nothing paid until the learner confirms. The learner adjusts in natural language; the
`PlanAdjuster` (Tier 1) classifies the sentence into a structural op, applied
deterministically here (Phase 1 operations) — the plan is never regenerated for a
structural tweak. Non-structural feedback escalates to a guided re-plan (Tier 2) via the
injected `replanner`. After every edit the course-fidelity union check re-runs; a
capability the learner gives up is warned about, never silently dropped.

Everything is injected (adjuster, replanner, input/output streams) so the whole loop is
tested with scripted `StringIO` conversations and zero real TTY.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from .fidelity import assess_course_fidelity
from .model import CourseSpec
from .operations import drop_module, force_single, merge_modules, reorder_modules

# The gate is bounded so a misfiring classifier or an indecisive learner cannot loop
# forever; hitting the cap cancels safely (nothing has been spent).
MAX_ADJUSTMENT_ROUNDS = 10

# ── Cost / time estimate (rough, order-of-magnitude; measured 2026-06) ──────────────
# One lesson run is ≈100K tokens across all stages and ~10–12 min wall-clock. The blended
# $/token is dominated by gpt-5 code_author/reviser; mini planner/critics are ~10x cheaper.
# These are expectation-setting figures, clearly labeled as rough, not a billing promise.
EST_TOKENS_PER_LESSON = 100_000
EST_MINUTES_PER_LESSON = (10, 12)
EST_USD_PER_TOKEN_LOW = 2.0e-6
EST_USD_PER_TOKEN_HIGH = 5.0e-6

_PROMPT = "Build this? (yes / no / describe a change) > "

# Wrap width for the objective bullets so a long objective doesn't run off the terminal.
_WRAP_WIDTH = 88
_BULLET_PAD = "        "  # objective bullets sit under their module header

# A callable that takes the current course + the learner's verbatim sentence and returns a
# re-planned course (CLI wires this to CurriculumPlanner.plan(..., guidance=sentence)).
Replanner = Callable[[CourseSpec, str], CourseSpec]


@dataclass(frozen=True)
class GateOutcome:
    """Result of the gate loop: whether to build, the final plan, and rounds consumed."""

    confirmed: bool
    course: CourseSpec
    rounds_used: int


# ── Rendering (pure) ────────────────────────────────────────────────────────────────


def render_plan(course: CourseSpec, original_capabilities: Sequence[str]) -> str:
    """Render the plan the way the learner sees it: numbered modules, one objective per
    (wrapped) line, compact builds-on links, a cost/time estimate, and the fidelity check."""
    count = len(course.modules)
    order_by_title = {module.spec.title: module.order for module in course.modules}

    lines = [f"Proposed plan ({count} module{'' if count == 1 else 's'}):", ""]
    for module in course.modules:
        header = f"  [{module.order}] {module.spec.title}"
        if module.module_prerequisites:
            refs = ", ".join(
                f"[{order_by_title[title]}]" if title in order_by_title else title
                for title in module.module_prerequisites
            )
            header += f"  (builds on {refs})"
        lines.append(header)
        for objective in module.spec.learning_objectives or ["(no objectives stated)"]:
            lines.append(_wrap_bullet(objective))
        lines.append("")

    lines.append(_render_estimate(count))
    lines.append(_render_fidelity(course, original_capabilities))
    return "\n".join(lines)


def _wrap_bullet(text: str) -> str:
    """One objective as a wrapped, hanging-indented bullet."""
    return textwrap.fill(
        text,
        width=_WRAP_WIDTH,
        initial_indent=f"{_BULLET_PAD}• ",
        subsequent_indent=f"{_BULLET_PAD}  ",
    )


def _render_estimate(module_count: int) -> str:
    low = EST_USD_PER_TOKEN_LOW * EST_TOKENS_PER_LESSON * module_count
    high = EST_USD_PER_TOKEN_HIGH * EST_TOKENS_PER_LESSON * module_count
    min_minutes = EST_MINUTES_PER_LESSON[0] * module_count
    max_minutes = EST_MINUTES_PER_LESSON[1] * module_count
    return (
        f"  Estimated cost: ~${low:.2f}–${high:.2f}  ·  "
        f"estimated time: ~{min_minutes}–{max_minutes} min  (rough)"
    )


def _render_fidelity(course: CourseSpec, original_capabilities: Sequence[str]) -> str:
    report = assess_course_fidelity(original_capabilities, course)
    if not report.missing:
        return "  ✓ Fidelity check: every requested capability is covered"
    lines = ["  ⚠ Fidelity check: some requested capabilities are no longer covered:"]
    lines.extend(_wrap_bullet(cap) for cap in report.missing)
    return "\n".join(lines)


# ── The loop ────────────────────────────────────────────────────────────────────────


def run_gate(
    course: CourseSpec,
    original_capabilities: Sequence[str],
    adjuster,
    replanner: Replanner,
    input_stream: TextIO,
    output_stream: TextIO,
    max_rounds: int = MAX_ADJUSTMENT_ROUNDS,
) -> GateOutcome:
    """Drive the interactive plan gate until confirm, cancel, EOF, or the round cap.

    Returns a confirmed GateOutcome only on an explicit yes; every other exit (no, EOF,
    round cap) is cancelled and nothing paid has run.
    """

    def emit(text: str) -> None:
        print(text, file=output_stream)

    rounds = 0
    while rounds < max_rounds:
        emit(render_plan(course, original_capabilities))
        emit("")
        output_stream.write(_PROMPT)
        output_stream.flush()

        line = input_stream.readline()
        if line == "":  # EOF — no decision was made; spend nothing.
            emit("No input received — nothing was run.")
            return GateOutcome(confirmed=False, course=course, rounds_used=rounds)

        rounds += 1
        sentence = line.strip()
        titles = tuple(module.spec.title for module in course.modules)
        intent = adjuster.classify(titles, sentence)

        if intent.op == "confirm":
            return GateOutcome(confirmed=True, course=course, rounds_used=rounds)
        if intent.op == "cancel":
            emit("Cancelled — nothing was run.")
            return GateOutcome(confirmed=False, course=course, rounds_used=rounds)

        if intent.op == "replan":
            try:
                course = replanner(course, intent.instruction)
            except Exception as exc:  # noqa: BLE001 — a failed re-plan keeps the plan
                emit(f"Re-planning failed: {exc}. Keeping the current plan.")
            continue

        # Structural ops: apply deterministically; a bad target re-prompts (counts a round).
        try:
            course, warning = _apply_structural(course, intent.op, intent.targets)
        except ValueError as exc:
            emit(f"Could not apply that change: {exc}")
            continue
        if warning:
            emit(warning)

    emit(f"Reached the {max_rounds}-round adjustment limit — nothing was run.")
    return GateOutcome(confirmed=False, course=course, rounds_used=rounds)


def _apply_structural(
    course: CourseSpec, op: str, targets: tuple[int, ...]
) -> tuple[CourseSpec, str]:
    """Apply one structural op, returning the new course and an optional learner warning.

    The warning surfaces exactly what an edit costs the learner (a drop's lost
    capabilities; a force_single packing everything into one lesson) so the choice is
    informed, never silent. Merge/reorder preserve all capabilities and need no warning.
    """
    if op == "merge":
        if len(targets) != 2:
            raise ValueError(f"merge needs exactly two module numbers, got {list(targets)}")
        return merge_modules(course, targets[0], targets[1]), ""

    if op == "drop":
        if not targets:
            raise ValueError("drop needs at least one module number")
        dropped_all: list[str] = []
        # Drop highest-first so earlier indices stay valid as the list shrinks.
        for target in sorted(targets, reverse=True):
            course, dropped = drop_module(course, target)
            dropped_all[:0] = dropped  # preserve original order across the reversed loop
        warning = (
            f"  ⚠ Dropped capabilities: {', '.join(dropped_all)}"
            if dropped_all
            else ""
        )
        return course, warning

    if op == "force_single":
        note = (
            "  ⚠ Packing every module into one lesson. If a single run cannot honestly "
            "hold all of it, the topic-fidelity detector will flag it rather than "
            "silently dropping a capability."
        )
        return force_single(course), note

    if op == "reorder":
        return reorder_modules(course, targets), ""

    raise ValueError(f"unknown structural op: {op!r}")
