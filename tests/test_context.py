"""Unit tests for the shared learner + topic context renderer."""

from __future__ import annotations

import pytest

from forged.context import build_context_block
from forged.models import LearnerProfile, TopicSpecification


def _learner() -> LearnerProfile:
    return LearnerProfile(
        name="Local LLM Learner",
        description="Engineer exploring local models.",
        prior_knowledge=["Python", "CLI basics"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="Wants to run models offline.",
    )


def _topic() -> TopicSpecification:
    return TopicSpecification(
        title="Building and Running a Local LLM",
        scope="implementation",
        learning_objectives=["Run a model locally", "Reason about memory"],
        prerequisites=["Python 3.11"],
        constraints="Must run on a laptop.",
        depth="intermediate",
        focus_areas=["setup", "inference"],
    )


@pytest.mark.unit
def test_returns_empty_string_when_no_context_provided():
    # Arrange / Act / Assert
    assert build_context_block(None, None) == ""


@pytest.mark.unit
def test_learner_only_includes_learner_and_omits_topic():
    block = build_context_block(_learner(), None)
    assert "Target learner — Local LLM Learner" in block
    assert "Python" in block
    assert "Topic —" not in block


@pytest.mark.unit
def test_topic_only_includes_topic_and_omits_learner():
    block = build_context_block(None, _topic())
    assert "Topic — Building and Running a Local LLM" in block
    assert "Run a model locally" in block
    assert "Target learner" not in block


@pytest.mark.unit
def test_both_render_under_heading_with_learner_before_topic():
    block = build_context_block(_learner(), _topic())
    assert block.startswith("## Lesson Context")
    assert block.index("Target learner") < block.index("Topic —")


@pytest.mark.unit
def test_both_carry_key_fields_from_each_model():
    block = build_context_block(_learner(), _topic())
    assert "Material density: standard" in block
    assert "Learning style: hands_on" in block
    assert "Depth: intermediate" in block
    assert "Constraints: Must run on a laptop." in block
    assert "setup" in block and "inference" in block


@pytest.mark.unit
def test_empty_list_field_renders_explicit_none():
    learner = _learner()
    bare_topic = TopicSpecification(
        title="X",
        scope="usage",
        learning_objectives=[],
        prerequisites=[],
        constraints="",
        depth="beginner",
        focus_areas=[],
    )
    block = build_context_block(learner, bare_topic)
    assert "(none)" in block
