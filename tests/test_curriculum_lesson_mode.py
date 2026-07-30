"""Tests for per-module lesson modes on the course plan (doc 18, D2/D3).

Modes used to be inferred only by the *lesson* planner, inside each module's build —
which is after the plan gate, so the operator could never see or change them. The
2026-07-28 run declared `executable` for all four modules, including one whose objective
was "design a local project and file layout", and nobody could intervene.

`ModuleSpec` now carries a provisional `lesson_mode` decided at decomposition time. It is
optional: `None` means "not decided here, let the lesson planner infer it", which keeps
the single-lesson path exactly as it was.

Merge rule (doc 18, Phase 3): a merged module inherits the **most executable** of its
parts, because a merged module inherits both deliverables and the stricter mode is the
one whose rigor covers both.
"""

from __future__ import annotations

import io
import json

import pytest

from forged.curriculum.gate import render_plan
from forged.curriculum.model import CourseSpec, ModuleSpec, course_to_dict
from forged.curriculum.operations import (
    drop_module,
    force_single,
    merge_modules,
    reorder_modules,
    set_mode,
)
from forged.curriculum.planner import COURSE_PLAN_RESPONSE_FORMAT, CurriculumPlanner
from forged.models import LearnerProfile, TopicSpecification


class _StubClient:
    """Returns a canned course-plan response; mirrors tests/test_curriculum_planner.py."""

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, system_prompt, user_prompt, trace_context=None, response_format=None) -> str:
        return self.response


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Kevin",
        description="Junior data scientist moving into AI engineering.",
        prior_knowledge=["Python"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="",
    )


def _plan_json(*modes: str | None) -> str:
    """A course-plan payload with one module per given mode (None omits the key)."""
    modules = []
    for index, mode in enumerate(modes):
        module: dict = {
            "title": f"Module {index}",
            "scope": "implementation",
            "depth": "intermediate",
            "learning_objectives": [f"objective {index}"],
            "prerequisites": [],
            "focus_areas": [],
            "module_prerequisites": [],
        }
        if mode is not None:
            module["lesson_mode"] = mode
        modules.append(module)
    return json.dumps({"title": "Course", "rationale": "split", "modules": modules})


def _topic(title: str) -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=[f"{title} obj"],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[],
    )


def _module(title: str, order: int, mode: str | None = None) -> ModuleSpec:
    return ModuleSpec(spec=_topic(title), order=order, lesson_mode=mode)


def _course(*modules: ModuleSpec) -> CourseSpec:
    return CourseSpec(title="Agents", modules=modules, rationale="split")


# ── The field itself ──────────────────────────────────────────────────────────────


def test_lesson_mode_defaults_to_none_so_the_lesson_planner_still_infers() -> None:
    # Arrange / Act
    module = ModuleSpec(spec=_topic("Fundamentals"), order=0)

    # Assert — None is "undecided", not a mode; the single-lesson path is unchanged.
    assert module.lesson_mode is None


def test_lesson_mode_round_trips_through_course_serialization() -> None:
    # Arrange
    course = _course(_module("Fundamentals", 0, "executable"), _module("Layout", 1, "artifact"))

    # Act
    data = course_to_dict(course)

    # Assert — the gate's decision must survive `--plan-only` persistence.
    assert [m["lesson_mode"] for m in data["modules"]] == ["executable", "artifact"]


# ── Carry-through across the gate's structural operations ─────────────────────────


def test_drop_module_preserves_the_surviving_modules_modes() -> None:
    # Arrange
    course = _course(
        _module("Fundamentals", 0, "executable"),
        _module("Harness", 1, "artifact"),
        _module("Tradeoffs", 2, "conceptual"),
    )

    # Act
    result, _dropped = drop_module(course, 1)

    # Assert
    assert [m.lesson_mode for m in result.modules] == ["executable", "conceptual"]


def test_reorder_modules_keeps_each_mode_with_its_own_module() -> None:
    # Arrange
    course = _course(
        _module("Fundamentals", 0, "executable"),
        _module("Harness", 1, "artifact"),
        _module("Tradeoffs", 2, "conceptual"),
    )

    # Act — reverse the order.
    result = reorder_modules(course, (2, 1, 0))

    # Assert — modes travel with their module, not with the position.
    assert [(m.spec.title, m.lesson_mode) for m in result.modules] == [
        ("Tradeoffs", "conceptual"),
        ("Harness", "artifact"),
        ("Fundamentals", "executable"),
    ]


@pytest.mark.parametrize(
    ("first_mode", "second_mode", "expected"),
    [
        ("artifact", "executable", "executable"),  # executable is the strictest
        ("executable", "artifact", "executable"),
        ("conceptual", "artifact", "artifact"),  # artifact outranks conceptual
        ("artifact", "conceptual", "artifact"),
        ("conceptual", "conceptual", "conceptual"),  # agreement is preserved
    ],
)
def test_merge_inherits_the_most_executable_mode(
    first_mode: str, second_mode: str, expected: str
) -> None:
    # Arrange — a merged module inherits both deliverables, so it needs the mode whose
    # rigor covers both (doc 18, Phase 3).
    course = _course(_module("A", 0, first_mode), _module("B", 1, second_mode))

    # Act
    result = merge_modules(course, 0, 1)

    # Assert
    assert result.modules[0].lesson_mode == expected


def test_merge_with_an_undecided_mode_stays_undecided_rather_than_guessing() -> None:
    # Arrange — None means "nobody decided yet"; merging must not invent a decision.
    course = _course(_module("A", 0, None), _module("B", 1, "artifact"))

    # Act
    result = merge_modules(course, 0, 1)

    # Assert — the lesson planner will infer it, exactly as if the merge never happened.
    assert result.modules[0].lesson_mode is None


def test_force_single_collapses_modes_to_the_most_executable() -> None:
    # Arrange
    course = _course(
        _module("Fundamentals", 0, "conceptual"),
        _module("Harness", 1, "artifact"),
        _module("Tuning", 2, "executable"),
    )

    # Act
    result = force_single(course)

    # Assert
    assert len(result.modules) == 1
    assert result.modules[0].lesson_mode == "executable"


# ── The course planner decides the provisional mode ───────────────────────────────


def test_planner_parses_a_mode_per_module() -> None:
    # Arrange — the whole point of doc 18: a course is normally MIXED.
    planner = CurriculumPlanner(
        llm_client=_StubClient(_plan_json("executable", "artifact", "conceptual"))
    )

    # Act
    course = planner.plan(brief="agents", learner_profile=_profile())

    # Assert
    assert [m.lesson_mode for m in course.modules] == ["executable", "artifact", "conceptual"]


def test_planner_leaves_mode_undecided_when_the_key_is_absent() -> None:
    # Arrange — older/other providers may omit it; that must not fabricate a mode.
    planner = CurriculumPlanner(llm_client=_StubClient(_plan_json(None)))

    # Act
    course = planner.plan(brief="agents", learner_profile=_profile())

    # Assert — None routes to the lesson planner's own inference, as before.
    assert course.modules[0].lesson_mode is None


def test_planner_rejects_an_unrecognized_mode_rather_than_passing_it_through() -> None:
    # Arrange — an invented word must never reach the gate or the lesson planner.
    planner = CurriculumPlanner(llm_client=_StubClient(_plan_json("interactive")))

    # Act
    course = planner.plan(brief="agents", learner_profile=_profile())

    # Assert
    assert course.modules[0].lesson_mode is None


def test_response_schema_constrains_lesson_mode_to_the_three_modes() -> None:
    # Arrange / Act — doc 15 parity: the contract is schema-enforced, not prompt-hoped.
    schema = COURSE_PLAN_RESPONSE_FORMAT["json_schema"]["schema"]
    module_schema = schema["properties"]["modules"]["items"]

    # Assert
    assert module_schema["properties"]["lesson_mode"]["enum"] == [
        "artifact",
        "conceptual",
        "executable",
    ]
    assert "lesson_mode" in module_schema["required"]


# ── A decided mode is handed down to the lesson planner as binding ────────────────


def _seeded_context(mode: str | None, tmp_path) -> str:
    """Seed a module store the way the course orchestrator does; return lesson_context."""
    from forged.curriculum.orchestrator import _seed_module_store

    store = _seed_module_store(tmp_path, _module("Project layout", 0, mode), _profile())
    return store.read_file("lesson_context.md")


def test_a_decided_mode_is_handed_down_to_the_lesson_planner(tmp_path) -> None:
    # Arrange / Act — the operator (or course planner) already decided; the lesson
    # planner must honor it rather than re-inferring and drifting back to executable.
    context = _seeded_context("artifact", tmp_path)

    # Assert
    assert "artifact" in context
    assert "lesson mode" in context.lower()


def test_an_undecided_mode_hands_down_nothing(tmp_path) -> None:
    # Arrange / Act — None must not inject a directive; the lesson planner infers freely.
    context = _seeded_context(None, tmp_path)

    # Assert
    assert "lesson mode" not in context.lower()


# ── Phase 4: the gate shows modes and can change them ─────────────────────────────


def test_render_plan_shows_each_modules_mode() -> None:
    # Arrange — the operator could not see modes at all before doc 18.
    course = _course(
        _module("Fundamentals", 0, "executable"),
        _module("Project layout", 1, "artifact"),
    )

    # Act
    rendered = render_plan(course, original_capabilities=[])

    # Assert
    assert "executable" in rendered
    assert "artifact" in rendered


def test_render_plan_flags_a_course_where_every_module_shares_one_mode() -> None:
    # Arrange — the exact 2026-07-28 shape: 4x executable, nobody noticed.
    course = _course(
        _module("A", 0, "executable"),
        _module("B", 1, "executable"),
        _module("C", 2, "executable"),
        _module("D", 3, "executable"),
    )

    # Act
    rendered = render_plan(course, original_capabilities=[])

    # Assert — a mixed course is the norm; sameness is worth a second look.
    assert "same mode" in rendered.lower()


def test_render_plan_does_not_flag_a_mixed_course() -> None:
    # Arrange
    course = _course(_module("A", 0, "executable"), _module("B", 1, "artifact"))

    # Act
    rendered = render_plan(course, original_capabilities=[])

    # Assert
    assert "same mode" not in rendered.lower()


def test_render_plan_omits_the_mode_line_when_undecided() -> None:
    # Arrange — a single-lesson/legacy plan carries no modes; don't invent a display.
    course = _course(_module("A", 0, None))

    # Act
    rendered = render_plan(course, original_capabilities=[])

    # Assert
    assert "mode" not in rendered.lower()


def test_set_mode_changes_one_module_and_leaves_the_rest_alone() -> None:
    # Arrange
    course = _course(_module("A", 0, "executable"), _module("B", 1, "executable"))

    # Act
    result = set_mode(course, 1, "conceptual")

    # Assert
    assert [m.lesson_mode for m in result.modules] == ["executable", "conceptual"]


def test_set_mode_never_mutates_the_input_course() -> None:
    # Arrange — immutability is enforced here, not aspirational (CLAUDE.md).
    course = _course(_module("A", 0, "executable"))

    # Act
    set_mode(course, 0, "artifact")

    # Assert
    assert course.modules[0].lesson_mode == "executable"


def test_set_mode_rejects_an_unknown_mode_word() -> None:
    # Arrange
    course = _course(_module("A", 0, "executable"))

    # Act / Assert — the gate turns this into a re-prompt, not a crash.
    with pytest.raises(ValueError, match="mode"):
        set_mode(course, 0, "interactive")


def test_set_mode_rejects_an_out_of_range_module() -> None:
    # Arrange
    course = _course(_module("A", 0, "executable"))

    # Act / Assert
    with pytest.raises(ValueError):
        set_mode(course, 7, "artifact")


# ── The gate loop applies a mode override ─────────────────────────────────────────


class _ScriptedAdjuster:
    """Returns a queued intent per call; mirrors tests/test_curriculum_gate.py's fake."""

    def __init__(self, *intents) -> None:
        self.intents = list(intents)

    def classify(self, module_titles, sentence):
        return self.intents.pop(0)


def _never_replans(course, instruction):  # pragma: no cover - must not be reached
    raise AssertionError("a mode override must not cost a re-plan")


def test_gate_applies_a_mode_override_without_replanning() -> None:
    # Arrange — "make module 1 conceptual", then "yes".
    from forged.curriculum.adjuster import AdjustmentIntent
    from forged.curriculum.gate import run_gate

    course = _course(_module("A", 0, "executable"), _module("B", 1, "executable"))
    adjuster = _ScriptedAdjuster(
        AdjustmentIntent(op="set_mode", targets=(1,), instruction="make module 1 conceptual"),
        AdjustmentIntent(op="confirm", targets=(), instruction="yes"),
    )

    # Act
    outcome = run_gate(
        course,
        original_capabilities=[],
        adjuster=adjuster,
        replanner=_never_replans,
        input_stream=io.StringIO("make module 1 conceptual\nyes\n"),
        output_stream=io.StringIO(),
    )

    # Assert
    assert outcome.confirmed is True
    assert [m.lesson_mode for m in outcome.course.modules] == ["executable", "conceptual"]


def test_gate_reprompts_when_the_sentence_names_no_recognizable_mode() -> None:
    # Arrange — a bad override must re-prompt, never crash the gate or spend money.
    from forged.curriculum.adjuster import AdjustmentIntent
    from forged.curriculum.gate import run_gate

    course = _course(_module("A", 0, "executable"))
    adjuster = _ScriptedAdjuster(
        AdjustmentIntent(op="set_mode", targets=(0,), instruction="make it nicer"),
        AdjustmentIntent(op="cancel", targets=(), instruction="no"),
    )
    output = io.StringIO()

    # Act
    outcome = run_gate(
        course,
        original_capabilities=[],
        adjuster=adjuster,
        replanner=_never_replans,
        input_stream=io.StringIO("make it nicer\nno\n"),
        output_stream=output,
    )

    # Assert
    assert outcome.confirmed is False
    assert "could not apply" in output.getvalue().lower()


# ── Review follow-ups: the mode-word parse must not invert or guess ───────────────


@pytest.mark.parametrize(
    "sentence",
    [
        "make module 2 non-executable, just explain it",
        "module 1 should not be executable",
        "no executable code in module 3 please",
    ],
)
def test_a_negated_mode_word_is_refused_rather_than_applied_backwards(sentence: str) -> None:
    """`re.findall` splits on '-', so "non-executable" used to yield "executable" and
    silently apply the OPPOSITE of what was asked — no crash, no re-prompt."""
    # Arrange / Act / Assert — refusing re-prompts; applying would be silently wrong.
    from forged.curriculum.gate import _mode_from_sentence

    with pytest.raises(ValueError):
        _mode_from_sentence(sentence)


def test_a_plain_mode_word_still_parses() -> None:
    # Arrange / Act / Assert — the guard must not break the happy path.
    from forged.curriculum.gate import _mode_from_sentence

    assert _mode_from_sentence("make module 2 conceptual") == "conceptual"
    assert _mode_from_sentence("artifact") == "artifact"
