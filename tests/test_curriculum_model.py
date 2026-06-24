"""Tests for the curriculum course data model (doc 13, Phase 1a).

A course is an ordered set of module specs; each module IS a TopicSpecification so
a module run is an ordinary agentic run. These objects are frozen value objects with
the same immutability discipline as PipelineState.
"""

from __future__ import annotations

import dataclasses

import pytest

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
