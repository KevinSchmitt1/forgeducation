"""Tests for the PlanAdjuster intent classifier (doc 16, Phase 2).

The adjuster turns one learner sentence into a structural AdjustmentIntent. Tests inject a
stub LLM client (no API key) and assert: the strict schema is forwarded, each op parses,
junk/unknown ops degrade to `replan`, and the model only ever sees titles + the sentence
(never full specs). The persona-contract tests pin the persona's mandates so a future edit
can't silently delete them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forged.curriculum.adjuster import (
    ADJUSTER_RESPONSE_FORMAT,
    AdjustmentIntent,
    PlanAdjuster,
)

_TITLES = ("Set up the local stack", "Fine-tune with LoRA", "Serve the model")


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


def _intent(op: str, targets: list[int], instruction: str = "x") -> str:
    return json.dumps({"op": op, "targets": targets, "instruction": instruction})


# ── T2.2 classifier behavior ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_loads_persona() -> None:
    adjuster = PlanAdjuster(llm_client=_StubClient("{}"))
    assert "Plan Adjuster" in adjuster.persona


@pytest.mark.unit
def test_defaults_to_gpt_5_mini() -> None:
    adjuster = PlanAdjuster(llm_client=_StubClient("{}"))
    assert adjuster.model == "gpt-5-mini"


@pytest.mark.unit
def test_forwards_strict_response_format() -> None:
    stub = _StubClient(_intent("confirm", []))
    PlanAdjuster(llm_client=stub).classify(_TITLES, "looks good")
    assert stub.response_format is ADJUSTER_RESPONSE_FORMAT
    assert stub.response_format["json_schema"]["strict"] is True
    assert stub.response_format["json_schema"]["name"] == "plan_adjustment_intent"


@pytest.mark.unit
@pytest.mark.parametrize(
    "op,targets",
    [
        ("confirm", []),
        ("cancel", []),
        ("force_single", []),
        ("merge", [0, 1]),
        ("drop", [2]),
        ("reorder", [0, 2, 1]),
        ("replan", []),
    ],
)
def test_each_op_parses(op: str, targets: list[int]) -> None:
    stub = _StubClient(_intent(op, targets, "the sentence"))
    intent = PlanAdjuster(llm_client=stub).classify(_TITLES, "the sentence")
    assert intent == AdjustmentIntent(
        op=op, targets=tuple(targets), instruction="the sentence"
    )


@pytest.mark.unit
def test_unknown_op_degrades_to_replan() -> None:
    stub = _StubClient(_intent("obliterate", [0], "wreck it"))
    intent = PlanAdjuster(llm_client=stub).classify(_TITLES, "wreck it")
    assert intent.op == "replan"
    assert intent.instruction == "wreck it"  # sentence preserved for Tier-2


@pytest.mark.unit
def test_unparseable_response_degrades_to_replan_with_sentence() -> None:
    stub = _StubClient("I cannot help with that.")
    intent = PlanAdjuster(llm_client=stub).classify(_TITLES, "hmm not sure")
    assert intent == AdjustmentIntent(op="replan", targets=(), instruction="hmm not sure")


@pytest.mark.unit
def test_llm_exception_degrades_to_replan() -> None:
    intent = PlanAdjuster(llm_client=_RaisingClient()).classify(_TITLES, "swap them")
    assert intent == AdjustmentIntent(op="replan", targets=(), instruction="swap them")


@pytest.mark.unit
def test_accepts_fenced_json() -> None:
    stub = _StubClient(f"```json\n{_intent('drop', [1])}\n```")
    intent = PlanAdjuster(llm_client=stub).classify(_TITLES, "drop it")
    assert intent.op == "drop"
    assert intent.targets == (1,)


@pytest.mark.unit
def test_user_message_contains_only_titles_and_sentence() -> None:
    stub = _StubClient(_intent("confirm", []))
    PlanAdjuster(llm_client=stub).classify(_TITLES, "yes please")
    msg = stub.user_prompt or ""
    for title in _TITLES:
        assert title in msg
    assert "yes please" in msg
    # No spec internals leak in — objectives/focus/scope/depth are never sent.
    for leaked in ("learning_objectives", "focus_areas", "scope", "depth", "prerequisites"):
        assert leaked not in msg


@pytest.mark.unit
def test_bad_target_entries_are_dropped_not_crashed() -> None:
    stub = _StubClient(
        json.dumps({"op": "merge", "targets": [0, "x", True, 1], "instruction": "s"})
    )
    intent = PlanAdjuster(llm_client=stub).classify(_TITLES, "s")
    assert intent.targets == (0, 1)  # non-ints and bools filtered


# ── T2.3 persona-contract tests ───────────────────────────────────────────────────

_PERSONA = (Path("personas") / "plan_adjuster.md").read_text(encoding="utf-8").lower()


@pytest.mark.unit
def test_persona_names_every_op_in_the_vocabulary() -> None:
    for op in ("merge", "drop", "force_single", "reorder", "replan", "confirm", "cancel"):
        assert op in _PERSONA, f"persona must document the '{op}' op"


@pytest.mark.unit
def test_persona_states_unsure_degrades_to_replan() -> None:
    assert "when unsure" in _PERSONA and "replan" in _PERSONA, (
        "persona must state the 'when unsure → replan' safety rule"
    )
    assert "never guess" in _PERSONA, "persona must forbid guessing a destructive op"


@pytest.mark.unit
def test_persona_requires_json_only_output() -> None:
    assert "only a single json object" in _PERSONA, (
        "persona must require JSON-only output (no prose/fence)"
    )


@pytest.mark.unit
def test_persona_states_targets_are_shown_module_numbers() -> None:
    assert "shown" in _PERSONA and "number" in _PERSONA, (
        "persona must define targets as the shown module numbers"
    )
