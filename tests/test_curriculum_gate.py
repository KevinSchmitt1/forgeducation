"""Tests for the interactive plan gate (doc 16, Phase 4).

The gate is fully injected — adjuster, replanner, and both streams are stubs — so every
path is exercised with a scripted `StringIO` conversation and no real TTY. A confirmed
outcome is returned only on an explicit yes; every other exit (no, EOF, round cap) is
cancelled with nothing paid having run.
"""

from __future__ import annotations

import io

import pytest

from forged.curriculum.adjuster import AdjustmentIntent
from forged.curriculum.gate import GateOutcome, render_plan, run_gate
from forged.curriculum.model import CourseSpec, ModuleSpec
from forged.models import TopicSpecification


def _topic(title: str, objectives: list[str], focus: list[str]) -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=objectives,
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=focus,
    )


def _module(title, order, objectives, focus, prereqs=()) -> ModuleSpec:
    return ModuleSpec(
        spec=_topic(title, objectives, focus), order=order, module_prerequisites=prereqs
    )


def _course() -> CourseSpec:
    return CourseSpec(
        title="Local LLMs",
        modules=(
            _module("Setup", 0, ["install stack"], ["device choice"]),
            _module("Train", 1, ["fine-tune with LoRA"], ["LoRA adapters"], ("Setup",)),
            _module("Serve", 2, ["serve the model"], ["inference"], ("Train",)),
        ),
        rationale="split",
    )


def _caps(course: CourseSpec) -> tuple[str, ...]:
    return course.all_capabilities


class _ScriptedAdjuster:
    """Pops a pre-scripted (op, targets) per call; echoes the real sentence as instruction
    (mirroring the persona's verbatim-echo contract). Repeats the last intent if exhausted."""

    def __init__(self, intents: list[tuple[str, list[int]]]) -> None:
        self._intents = list(intents)
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def classify(self, module_titles: tuple[str, ...], sentence: str) -> AdjustmentIntent:
        self.calls.append((module_titles, sentence))
        op, targets = self._intents[0] if len(self._intents) == 1 else self._intents.pop(0)
        return AdjustmentIntent(op=op, targets=tuple(targets), instruction=sentence)


class _RecordingReplanner:
    def __init__(self, new_course: CourseSpec | None = None, exc: Exception | None = None):
        self._new_course = new_course
        self._exc = exc
        self.calls: list[tuple[CourseSpec, str]] = []

    def __call__(self, course: CourseSpec, instruction: str) -> CourseSpec:
        self.calls.append((course, instruction))
        if self._exc is not None:
            raise self._exc
        return self._new_course if self._new_course is not None else course


def _run(course, adjuster, replanner, script: str, max_rounds: int = 10):
    out = io.StringIO()
    outcome = run_gate(
        course,
        _caps(course),
        adjuster,
        replanner,
        input_stream=io.StringIO(script),
        output_stream=out,
        max_rounds=max_rounds,
    )
    return outcome, out.getvalue()


# ── T4.1 render_plan ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_render_shows_modules_objectives_and_builds_on() -> None:
    text = render_plan(_course(), _caps(_course()))
    assert "[0] Setup" in text and "[1] Train" in text and "[2] Serve" in text
    assert "install stack" in text  # objective shown
    assert "builds on [0]" in text  # prerequisite link shown as a compact index reference


@pytest.mark.unit
def test_render_puts_each_objective_on_its_own_bullet_line() -> None:
    course = CourseSpec(
        title="C",
        modules=(_module("Setup", 0, ["install the stack", "verify the install"], []),),
        rationale="",
    )
    text = render_plan(course, _caps(course))
    # Two objectives → two bullet lines, not one semicolon-joined blob.
    assert "• install the stack" in text
    assert "• verify the install" in text
    assert "install the stack; verify the install" not in text


@pytest.mark.unit
def test_render_shows_cost_and_time_estimate_scaled_by_modules() -> None:
    text = render_plan(_course(), _caps(_course()))
    assert "Estimated cost:" in text and "estimated time:" in text
    # 3 modules × 10–12 min each.
    assert "~30–36 min" in text


@pytest.mark.unit
def test_render_shows_fidelity_ok_when_all_covered() -> None:
    course = _course()
    text = render_plan(course, _caps(course))
    assert "✓ Fidelity check" in text


@pytest.mark.unit
def test_render_shows_fidelity_warning_when_capability_missing() -> None:
    course = _course()
    original = (*_caps(course), "deploy to a phone")  # a capability no module covers
    text = render_plan(course, original)
    assert "⚠ Fidelity check" in text
    assert "deploy to a phone" in text


# ── T4.2 run_gate ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_confirm_first_try_returns_confirmed() -> None:
    adjuster = _ScriptedAdjuster([("confirm", [])])
    outcome, _out = _run(_course(), adjuster, _RecordingReplanner(), "yes\n")
    assert outcome == GateOutcome(confirmed=True, course=_course(), rounds_used=1)


@pytest.mark.unit
def test_cancel_returns_cancelled_and_says_nothing_ran() -> None:
    adjuster = _ScriptedAdjuster([("cancel", [])])
    outcome, out = _run(_course(), adjuster, _RecordingReplanner(), "no\n")
    assert outcome.confirmed is False
    assert "nothing was run" in out.lower()


@pytest.mark.unit
def test_merge_then_confirm_reduces_module_count() -> None:
    adjuster = _ScriptedAdjuster([("merge", [0, 1]), ("confirm", [])])
    outcome, _out = _run(_course(), adjuster, _RecordingReplanner(), "combine 1 and 2\nyes\n")
    assert outcome.confirmed is True
    assert len(outcome.course.modules) == 2
    assert outcome.rounds_used == 2


@pytest.mark.unit
def test_force_single_emits_packing_warning() -> None:
    adjuster = _ScriptedAdjuster([("force_single", []), ("confirm", [])])
    outcome, out = _run(_course(), adjuster, _RecordingReplanner(), "one notebook\nyes\n")
    assert outcome.confirmed is True
    assert len(outcome.course.modules) == 1
    assert "Packing every module" in out


@pytest.mark.unit
def test_drop_reports_dropped_capabilities() -> None:
    adjuster = _ScriptedAdjuster([("drop", [1]), ("confirm", [])])
    _outcome, out = _run(_course(), adjuster, _RecordingReplanner(), "drop 2\nyes\n")
    assert "Dropped capabilities" in out
    assert "fine-tune with LoRA" in out


@pytest.mark.unit
def test_replan_calls_replanner_with_verbatim_sentence() -> None:
    replanner = _RecordingReplanner(new_course=_course())
    adjuster = _ScriptedAdjuster([("replan", []), ("confirm", [])])
    sentence = "module 2 should focus on quantization instead"
    outcome, _out = _run(_course(), adjuster, replanner, f"{sentence}\nyes\n")
    assert outcome.confirmed is True
    assert replanner.calls[0][1] == sentence  # verbatim


@pytest.mark.unit
def test_replan_failure_keeps_plan_and_continues() -> None:
    replanner = _RecordingReplanner(exc=ValueError("planner blew up"))
    adjuster = _ScriptedAdjuster([("replan", []), ("confirm", [])])
    outcome, out = _run(_course(), adjuster, replanner, "change it\nyes\n")
    assert outcome.confirmed is True
    assert "Re-planning failed" in out
    assert len(outcome.course.modules) == 3  # unchanged


@pytest.mark.unit
def test_op_value_error_reprompts_and_counts_a_round() -> None:
    # merge with one target is invalid → re-prompt; then confirm.
    adjuster = _ScriptedAdjuster([("merge", [0]), ("confirm", [])])
    outcome, out = _run(_course(), adjuster, _RecordingReplanner(), "merge it\nyes\n")
    assert outcome.confirmed is True
    assert "Could not apply that change" in out
    assert outcome.rounds_used == 2


@pytest.mark.unit
def test_round_cap_terminates_cancelled() -> None:
    # Identity reorder is a valid no-op that never confirms → hits the cap.
    adjuster = _ScriptedAdjuster([("reorder", [0, 1, 2])])
    outcome, out = _run(_course(), adjuster, _RecordingReplanner(), "shuffle\n" * 5, max_rounds=3)
    assert outcome.confirmed is False
    assert outcome.rounds_used == 3
    assert "3-round" in out


@pytest.mark.unit
def test_eof_terminates_cancelled_without_spending() -> None:
    outcome, out = _run(_course(), _ScriptedAdjuster([("confirm", [])]), _RecordingReplanner(), "")
    assert outcome.confirmed is False
    assert outcome.rounds_used == 0
    assert "No input received" in out


@pytest.mark.unit
def test_adjuster_receives_titles_only_context() -> None:
    adjuster = _ScriptedAdjuster([("confirm", [])])
    _run(_course(), adjuster, _RecordingReplanner(), "yes\n")
    titles, sentence = adjuster.calls[0]
    assert titles == ("Setup", "Train", "Serve")
    assert sentence == "yes"
