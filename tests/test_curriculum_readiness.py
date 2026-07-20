"""Tests for the ReadinessAssessor pre-flight check (doc 14, Part III).

The assessor judges whether a topic sized to a single module is honestly reachable for a
learner, BEFORE any lesson is built. Tests inject a stub LLM client (no API key) and assert:
the strict schema is forwarded, a reachable/unreachable verdict parses, an unparseable
response or LLM exception fails OPEN (reachable=True — conservative spend, never blocks a
build the assessor couldn't judge), and the model only ever sees brief + learner context +
topic_spec (never a plan or notebook). Persona-contract tests pin the persona's mandates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forged.curriculum.readiness import READINESS_RESPONSE_FORMAT, ReadinessAssessor
from forged.models import LearnerProfile, TopicSpecification


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Kevin",
        description="Junior DS moving into AI engineering.",
        prior_knowledge=["Python"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="DS to AI engineering.",
    )


def _topic_spec(title: str = "Train a model with LoRA") -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=["fine-tune with LoRA"],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[],
    )


class _StubClient:
    """Records the prompts + response_format it was called with; returns a canned reply."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None
        self.response_format: dict | None = None

    def complete(self, system_prompt, user_prompt, response_format=None) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.response_format = response_format
        return self.response


class _RaisingClient:
    def complete(self, system_prompt, user_prompt, response_format=None) -> str:
        raise RuntimeError("boom")


def _verdict_json(
    reachable: bool,
    beachhead: str = "",
    missing_foundations: list[str] | None = None,
    unreachable_capabilities: list[str] | None = None,
    reason: str = "",
) -> str:
    return json.dumps(
        {
            "reachable": reachable,
            "beachhead": beachhead,
            "missing_foundations": missing_foundations or [],
            "unreachable_capabilities": unreachable_capabilities or [],
            "reason": reason,
        }
    )


# ── assessor behavior ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_loads_persona() -> None:
    assessor = ReadinessAssessor(llm_client=_StubClient("{}"))
    assert "Readiness Assessor" in assessor.persona


@pytest.mark.unit
def test_defaults_to_gpt_5_mini() -> None:
    assessor = ReadinessAssessor(llm_client=_StubClient("{}"))
    assert assessor.model == "gpt-5-mini"


@pytest.mark.unit
def test_forwards_strict_response_format() -> None:
    stub = _StubClient(_verdict_json(True))
    ReadinessAssessor(llm_client=stub).assess("topic", _profile(), _topic_spec())
    assert stub.response_format is READINESS_RESPONSE_FORMAT
    assert stub.response_format["json_schema"]["strict"] is True
    assert stub.response_format["json_schema"]["name"] == "readiness_verdict"


@pytest.mark.unit
def test_reachable_verdict_parses() -> None:
    stub = _StubClient(_verdict_json(True, reason="gaps are shallow"))
    verdict = ReadinessAssessor(llm_client=stub).assess("topic", _profile(), _topic_spec())
    assert verdict.reachable is True
    assert verdict.beachhead == ""
    assert verdict.missing_foundations == ()
    assert verdict.unreachable_capabilities == ()
    assert verdict.reason == "gaps are shallow"


@pytest.mark.unit
def test_unreachable_verdict_parses_full_shape() -> None:
    stub = _StubClient(
        _verdict_json(
            False,
            beachhead="load a pretrained model and generate text",
            missing_foundations=["what a tensor is", "what training a neural net does"],
            unreachable_capabilities=["fine-tune with LoRA"],
            reason="requires prerequisites the learner lacks: tensors, neural net training",
        )
    )
    verdict = ReadinessAssessor(llm_client=stub).assess("topic", _profile(), _topic_spec())
    assert verdict.reachable is False
    assert verdict.beachhead == "load a pretrained model and generate text"
    assert verdict.missing_foundations == (
        "what a tensor is", "what training a neural net does",
    )
    assert verdict.unreachable_capabilities == ("fine-tune with LoRA",)
    assert "requires prerequisites the learner lacks" in verdict.reason


@pytest.mark.unit
def test_unparseable_response_fails_open_reachable() -> None:
    """A response the assessor can't parse must never block a build it couldn't judge —
    fail open (reachable=True), mirroring PlanAdjuster's degrade-to-safe-default stance."""
    stub = _StubClient("I cannot help with that.")
    verdict = ReadinessAssessor(llm_client=stub).assess("topic", _profile(), _topic_spec())
    assert verdict.reachable is True


@pytest.mark.unit
def test_llm_exception_fails_open_reachable() -> None:
    verdict = ReadinessAssessor(llm_client=_RaisingClient()).assess(
        "topic", _profile(), _topic_spec()
    )
    assert verdict.reachable is True


@pytest.mark.unit
def test_missing_reachable_field_fails_open() -> None:
    stub = _StubClient(json.dumps({"beachhead": "", "reason": "no verdict field"}))
    verdict = ReadinessAssessor(llm_client=stub).assess("topic", _profile(), _topic_spec())
    assert verdict.reachable is True


@pytest.mark.unit
def test_accepts_fenced_json() -> None:
    stub = _StubClient(f"```json\n{_verdict_json(True)}\n```")
    verdict = ReadinessAssessor(llm_client=stub).assess("topic", _profile(), _topic_spec())
    assert verdict.reachable is True


@pytest.mark.unit
def test_context_guard_only_brief_learner_context_and_topic_spec_reach_the_prompt() -> None:
    """The model must never see a lesson plan or notebook — only brief + learner
    context + topic_spec (this is a pre-execution check, nothing has been built yet)."""
    stub = _StubClient(_verdict_json(True))
    ReadinessAssessor(llm_client=stub).assess(
        "setup and train local LLMs", _profile(), _topic_spec()
    )
    msg = stub.user_prompt or ""
    assert "setup and train local LLMs" in msg
    assert "Python" in msg  # prior knowledge from the learner profile
    assert "fine-tune with LoRA" in msg  # topic spec's learning objectives
    for leaked in ("lesson.ipynb", "code_author", "```python"):
        assert leaked not in msg


@pytest.mark.unit
def test_assess_without_topic_spec() -> None:
    stub = _StubClient(_verdict_json(True))
    verdict = ReadinessAssessor(llm_client=stub).assess("bare topic", _profile(), None)
    assert verdict.reachable is True
    assert "bare topic" in (stub.user_prompt or "")


# ── persona-contract tests ────────────────────────────────────────────────────────

_PERSONA = (Path("personas") / "readiness_assessor.md").read_text(encoding="utf-8").lower()


@pytest.mark.unit
def test_persona_documents_the_verdict_vocabulary() -> None:
    for term in (
        "reachable", "beachhead", "missing_foundations", "unreachable_capabilities", "reason",
    ):
        assert term in _PERSONA, f"persona must document the '{term}' field"


@pytest.mark.unit
def test_persona_requires_the_honest_reason_phrase() -> None:
    assert "requires prerequisites the learner lacks" in _PERSONA, (
        "persona must mandate the same honest reason phrase as the lesson planner's "
        "own readiness verdict"
    )


@pytest.mark.unit
def test_persona_requires_json_only_output() -> None:
    assert "only a single json object" in _PERSONA, (
        "persona must require JSON-only output (no prose/fence)"
    )


@pytest.mark.unit
def test_persona_turns_on_foundational_and_too_deep_gaps() -> None:
    assert "foundational" in _PERSONA, "verdict must turn on whether gaps are foundational"
