"""The offline demo LLM behind `forged ui --fake-llm` — driven through the real agents,
so its answers are proven to parse exactly as a real model's would."""

from __future__ import annotations

import pytest

import forged.cli as cli
from forged.curriculum.adjuster import PlanAdjuster
from forged.curriculum.fidelity import assess_course_fidelity
from forged.curriculum.planner import CurriculumPlanner
from forged.curriculum.readiness import ReadinessAssessor
from forged.models import TopicSpecification
from forged.ui.fake_llm import FakeLLM


def _spec(objectives: list[str]) -> TopicSpecification:
    return TopicSpecification(
        title="Hash maps",
        scope="implementation",
        learning_objectives=objectives,
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=["collisions"],
    )


def _planner() -> CurriculumPlanner:
    return CurriculumPlanner(personas_dir=cli.DEFAULT_PERSONAS, llm_client=FakeLLM())


@pytest.mark.unit
def test_fake_plan_is_a_mixed_mode_three_module_course_covering_every_capability() -> None:
    spec = _spec(["Build a hash map", "Resize the table", "Measure load factor"])

    course = _planner().plan("Hash maps", cli._default_learner_profile(), spec)

    assert len(course.modules) == 3
    assert [m.lesson_mode for m in course.modules] == ["executable", "artifact", "conceptual"]
    capabilities = [*spec.learning_objectives, *spec.focus_areas]
    assert assess_course_fidelity(capabilities, course).is_faithful
    assert course.modules[1].module_prerequisites == (course.modules[0].spec.title,)


@pytest.mark.unit
def test_fake_replan_asking_for_a_single_lesson_returns_one_module() -> None:
    course = _planner().plan(
        "Hash maps", cli._default_learner_profile(), _spec(["Build a hash map"]),
        guidance="make it a single lesson",
    )

    assert len(course.modules) == 1
    assert "single lesson" in course.rationale


@pytest.mark.unit
def test_fake_readiness_is_always_reachable() -> None:
    assessor = ReadinessAssessor(personas_dir=cli.DEFAULT_PERSONAS, llm_client=FakeLLM())

    verdict = assessor.assess("Hash maps", cli._default_learner_profile(), _spec(["x"]))

    assert verdict.reachable


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sentence", "op", "targets", "instruction"),
    [
        ("yes", "confirm", (), None),
        ("cancel", "cancel", (), None),
        ("merge 0 and 1", "merge", (0, 1), None),
        ("drop module 2", "drop", (2,), None),
        ("swap 0 and 2", "reorder", (2, 1, 0), None),
        ("make module 1 conceptual", "set_mode", (1,), "conceptual"),
        ("just one notebook please", "force_single", (), None),
        ("focus more on collisions", "replan", (), None),
    ],
)
def test_fake_adjuster_classifies_the_gate_vocabulary(
    sentence: str, op: str, targets: tuple[int, ...], instruction: str | None
) -> None:
    adjuster = PlanAdjuster(personas_dir=cli.DEFAULT_PERSONAS, llm_client=FakeLLM())

    intent = adjuster.classify(("A", "B", "C"), sentence)

    assert (intent.op, intent.targets) == (op, targets)
    if instruction:
        assert intent.instruction == instruction


@pytest.mark.unit
def test_fake_llm_refuses_a_lesson_pipeline_call() -> None:
    with pytest.raises(RuntimeError, match="no canned answer"):
        FakeLLM().complete("s", "u")
