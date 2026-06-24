"""Tests for the course-level fidelity (union-coverage) check (doc 13, Phase 1b).

The honesty invariant: the union of the modules' capabilities must cover every
capability the original topic requested. The planner may *distribute* capabilities
across modules; it may never *drop* one. This reuses R1's distinctive-term coverage
logic (`forged.pipeline.fidelity`) so the course check and the per-module R1 detector
judge the same way.
"""

from __future__ import annotations

import pytest

from forged.curriculum.fidelity import assess_course_fidelity
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


def _module(title: str, objectives: list[str], order: int) -> ModuleSpec:
    return ModuleSpec(spec=_topic(title, objectives, []), order=order)


@pytest.mark.unit
def test_course_covering_all_capabilities_is_faithful() -> None:
    """Setup + train split: each original capability lands in some module."""
    original = ["install and verify the PyTorch stack", "fine-tune a model with LoRA"]
    course = CourseSpec(
        title="Local LLMs",
        modules=(
            _module("Setup", ["install and verify the PyTorch stack"], 0),
            _module("Training", ["fine-tune a model with LoRA"], 1),
        ),
        rationale="split setup from training",
    )
    report = assess_course_fidelity(original, course)
    assert report.is_faithful
    assert report.missing == ()


@pytest.mark.unit
def test_course_dropping_a_capability_is_not_faithful() -> None:
    """If no module covers the training capability, the check surfaces it honestly."""
    original = ["install and verify the PyTorch stack", "fine-tune a model with LoRA"]
    course = CourseSpec(
        title="Local LLMs",
        modules=(_module("Setup", ["install and verify the PyTorch stack"], 0),),
        rationale="only setup — training silently dropped",
    )
    report = assess_course_fidelity(original, course)
    assert not report.is_faithful
    assert "fine-tune a model with LoRA" in report.missing


@pytest.mark.unit
def test_no_original_capabilities_is_vacuously_faithful() -> None:
    course = CourseSpec(title="Empty", modules=(), rationale="")
    report = assess_course_fidelity([], course)
    assert report.is_faithful
    assert report.covered == () and report.missing == ()
