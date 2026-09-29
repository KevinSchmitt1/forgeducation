"""Tests for the curriculum course data model (doc 13, Phase 1a).

A course is an ordered set of module specs; each module IS a TopicSpecification so
a module run is an ordinary agentic run. These objects are frozen value objects with
the same immutability discipline as PipelineState.
"""

from __future__ import annotations

import dataclasses

import pytest

from forged.curriculum.model import (
    CourseResult,
    CourseSpec,
    ModuleResult,
    ModuleSpec,
    ReadinessVerdict,
    course_from_dict,
    course_to_dict,
)
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


@pytest.mark.unit
def test_module_spec_is_frozen() -> None:
    module = ModuleSpec(spec=_topic("Setup", ["install stack"], []), order=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        module.order = 1  # type: ignore[misc]


@pytest.mark.unit
def test_module_prerequisites_default_empty_tuple() -> None:
    module = ModuleSpec(spec=_topic("Setup", ["install"], []), order=0)
    assert module.module_prerequisites == ()


@pytest.mark.unit
def test_remediation_for_defaults_empty_tuple() -> None:
    """A proactively-planned module (not a reactive remediation) has an empty
    remediation_for — the assembler uses this to tell the two kinds apart."""
    module = ModuleSpec(spec=_topic("Setup", ["install"], []), order=0)
    assert module.remediation_for == ()


@pytest.mark.unit
def test_remediation_for_records_the_dropped_capabilities() -> None:
    module = ModuleSpec(
        spec=_topic("Fine-tuning", ["fine-tune with LoRA"], []),
        order=2,
        remediation_for=("fine-tune with LoRA",),
    )
    assert module.remediation_for == ("fine-tune with LoRA",)


@pytest.mark.unit
def test_module_capabilities_are_objectives_plus_focus() -> None:
    """Mirror R1's capability derivation (learning_objectives + focus_areas) so the
    course-level fidelity check agrees with the per-module one."""
    module = ModuleSpec(
        spec=_topic("Train", ["fine-tune with LoRA"], ["LoRA adapters"]), order=1
    )
    assert module.capabilities == ("fine-tune with LoRA", "LoRA adapters")


@pytest.mark.unit
def test_course_spec_is_frozen() -> None:
    course = CourseSpec(title="Local LLMs", modules=(), rationale="why")
    with pytest.raises(dataclasses.FrozenInstanceError):
        course.title = "x"  # type: ignore[misc]


@pytest.mark.unit
def test_course_all_capabilities_is_ordered_union() -> None:
    """The union of module capabilities — ordered, de-duplicated — is what the
    honesty invariant checks against the original topic."""
    m0 = ModuleSpec(spec=_topic("Setup", ["install stack"], ["device choice"]), order=0)
    m1 = ModuleSpec(
        spec=_topic("Train", ["fine-tune with LoRA"], ["install stack"]), order=1
    )
    course = CourseSpec(title="Local LLMs", modules=(m0, m1), rationale="split")
    # "install stack" appears in both → present once, first occurrence wins ordering.
    assert course.all_capabilities == (
        "install stack",
        "device choice",
        "fine-tune with LoRA",
    )


@pytest.mark.unit
def test_module_result_is_frozen() -> None:
    module = ModuleSpec(spec=_topic("Setup", ["install"], []), order=0)
    result = ModuleResult(
        module=module, run_dir="/tmp/m0", terminal_ok=True,
        notebook_path="/tmp/m0/lesson.ipynb", topic_fidelity=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.terminal_ok = False  # type: ignore[misc]


@pytest.mark.unit
def test_course_result_is_frozen_and_holds_module_results() -> None:
    module = ModuleSpec(spec=_topic("Setup", ["install"], []), order=0)
    mr = ModuleResult(
        module=module, run_dir="/tmp/m0", terminal_ok=True,
        notebook_path=None, topic_fidelity=(),
    )
    course = CourseSpec(title="C", modules=(module,), rationale="")
    result = CourseResult(course=course, modules=(mr,))
    assert result.modules[0].run_dir == "/tmp/m0"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.modules = ()  # type: ignore[misc]


# ── ReadinessVerdict (doc 14, Part III) ─────────────────────────────────────────


@pytest.mark.unit
def test_readiness_verdict_is_frozen() -> None:
    verdict = ReadinessVerdict(
        reachable=True, beachhead="", missing_foundations=(),
        unreachable_capabilities=(), reason="",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.reachable = False  # type: ignore[misc]


@pytest.mark.unit
def test_readiness_verdict_holds_an_unreachable_topic() -> None:
    verdict = ReadinessVerdict(
        reachable=False,
        beachhead="load a pretrained model and generate text",
        missing_foundations=("what a tensor is", "what training a neural net does"),
        unreachable_capabilities=("fine-tune with LoRA",),
        reason="requires prerequisites the learner lacks: tensors, neural net training",
    )
    assert verdict.reachable is False
    assert verdict.missing_foundations == (
        "what a tensor is", "what training a neural net does",
    )
    assert verdict.unreachable_capabilities == ("fine-tune with LoRA",)


# ── course_from_dict round-trip (Lane 7, doc 25 — the UI ↔ backend seam) ──────────


def _rich_course() -> CourseSpec:
    """A multi-module course exercising every serialized field: tuple prerequisites,
    reactive remediation, a decided lesson_mode, and an undecided (None) one."""
    m0 = ModuleSpec(
        spec=_topic("Setup", ["install stack"], ["device choice"]),
        order=0,
        lesson_mode="artifact",
    )
    m1 = ModuleSpec(
        spec=_topic("Train", ["fine-tune with LoRA"], ["LoRA adapters"]),
        order=1,
        module_prerequisites=("Setup",),
        remediation_for=("fine-tune with LoRA",),
        lesson_mode="executable",
    )
    m2 = ModuleSpec(
        spec=_topic("Concepts", ["reason about tradeoffs"], []),
        order=2,
        module_prerequisites=("Setup", "Train"),
    )
    return CourseSpec(title="Local LLMs", modules=(m0, m1, m2), rationale="split by phase")


@pytest.mark.unit
def test_course_from_dict_round_trips_object_identity() -> None:
    """course_from_dict(course_to_dict(c)) == c — the object survives the JSON hop."""
    course = _rich_course()
    assert course_from_dict(course_to_dict(course)) == course


@pytest.mark.unit
def test_course_to_dict_round_trips_dict_identity() -> None:
    """course_to_dict(course_from_dict(d)) == d — the dict survives reconstruction."""
    data = course_to_dict(_rich_course())
    assert course_to_dict(course_from_dict(data)) == data


@pytest.mark.unit
def test_course_from_dict_restores_frozen_tuples_not_lists() -> None:
    """asdict flattens the frozen tuples into lists; reconstruction must restore them so
    the value objects compare equal and stay immutable."""
    course = course_from_dict(course_to_dict(_rich_course()))
    assert isinstance(course.modules, tuple)
    assert isinstance(course.modules[1].module_prerequisites, tuple)
    assert isinstance(course.modules[1].remediation_for, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        course.modules[0].order = 9  # type: ignore[misc]


@pytest.mark.unit
def test_course_from_dict_handles_empty_modules() -> None:
    course = CourseSpec(title="Empty", modules=(), rationale="")
    assert course_from_dict(course_to_dict(course)) == course


@pytest.mark.unit
def test_course_from_dict_defaults_absent_optional_module_fields() -> None:
    """A minimal module dict (older/partial JSON) falls back to the model's defaults."""
    data = {
        "title": "C",
        "modules": [
            {
                "spec": {
                    "title": "Only",
                    "scope": "implementation",
                    "learning_objectives": ["do a thing"],
                    "prerequisites": [],
                    "constraints": "",
                    "depth": "beginner",
                    "focus_areas": [],
                },
                "order": 0,
            }
        ],
    }
    course = course_from_dict(data)
    assert course.rationale == ""
    assert course.modules[0].module_prerequisites == ()
    assert course.modules[0].remediation_for == ()
    assert course.modules[0].lesson_mode is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.pop("title"), "'title' must be a string"),
        (lambda d: d.__setitem__("modules", "nope"), "'modules' must be a list"),
        (
            lambda d: d["modules"][0].__setitem__("order", "x"),
            "'order' must be an integer",
        ),
        (
            lambda d: d["modules"][0].__setitem__("lesson_mode", "bogus"),
            "'lesson_mode' must be null or one of",
        ),
        (
            lambda d: d["modules"][0]["spec"].pop("learning_objectives"),
            "missing field",
        ),
        (
            lambda d: d["modules"][0]["spec"].__setitem__("focus_areas", "flat"),
            "must be a list of strings",
        ),
        (lambda d: d.__setitem__("rationale", 5), "'rationale' must be a string"),
        (
            lambda d: d.__setitem__("modules", ["not-a-dict"]),
            "module 0 must be a JSON object",
        ),
        (
            lambda d: d["modules"][0].__setitem__("spec", "not-a-dict"),
            "'spec' must be a JSON object",
        ),
        (
            lambda d: d["modules"][0].__setitem__("module_prerequisites", "Setup"),
            "'module_prerequisites' must be a list of strings",
        ),
    ],
)
def test_course_from_dict_rejects_malformed_input(mutate, message) -> None:
    """The UI seam is a boundary: bad JSON raises a locating ValueError, not a crash
    deep in the dataclass constructor."""
    data = course_to_dict(_rich_course())
    mutate(data)
    with pytest.raises(ValueError, match=message):
        course_from_dict(data)


@pytest.mark.unit
def test_course_from_dict_rejects_non_dict() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        course_from_dict(["not", "a", "dict"])  # type: ignore[arg-type]
