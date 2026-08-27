"""Persona-contract tests for the goal-fit verdict (doc 22, D6/R5).

The rubric asks how well the code that exists is presented; nothing asks whether it
should exist. R5 puts that question to both critics — from their own side, which is
doc 22's open question 2 answered in the affirmative:

  * Student  — "was this too much, or too little, for *me* to reach the goal?"
  * Reviewer — "was this the right material at all?"

The asymmetry is enforced in code too (`RevisorAgent._coerce_goal_fit(allow_drift=…)`
and the per-critic JSON schema), because a persona is advisory and `drifted` is the one
verdict that routes to the planner. These tests pin the *instruction*; the code tests
pin the *enforcement*. Both are needed: the schema stops a rogue verdict, only the
persona makes a good one likely.

Same shape as `test_verifiability_persona.py` and `test_critic_budget_persona.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PERSONAS = Path("personas")
CRITICS = ("student.md", "reviewer.md")


def _read(name: str) -> str:
    """Lowercased with whitespace collapsed (persona prose is hard-wrapped)."""
    raw = (PERSONAS / name).read_text(encoding="utf-8")
    assert raw.strip(), f"{name} should not be empty"
    return " ".join(raw.replace(">", " ").lower().split())


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_is_asked_whether_the_code_earns_its_place(persona: str) -> None:
    """The question the rubric never asked (doc 22, Part II)."""
    text = _read(persona)

    assert "earn its place" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_emits_the_verdict_in_its_json(persona: str) -> None:
    """A judgement that never reaches the JSON never reaches the classifier."""
    text = _read(persona)

    assert "goal_fit" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_has_both_directions_of_the_necessity_axis(persona: str) -> None:
    """Overwhelming *and* insufficient — a grader offered one direction says "fine"."""
    text = _read(persona)

    assert "overwhelming" in text
    assert "insufficient" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_the_verdict_is_mode_aware(persona: str) -> None:
    """An artifact lesson is judged on the artifact, not on impressive computation.

    Same rule as the anti-hollow gate: the mode changes what "earning its place"
    means, so the question must be asked in the mode's own terms.
    """
    text = _read(persona)

    assert "would keep" in text


@pytest.mark.unit
def test_only_the_reviewer_may_call_the_subject_drifted() -> None:
    """`drifted` is the one problem that routes to the planner, so it is the expert's.

    A replan can delete the capability the topic asked for (doc 11), which is why a
    simulated novice must not be able to trigger one. The student's schema does not
    offer the label and `_coerce_goal_fit(allow_drift=False)` strips it — the persona
    must not invite it either.
    """
    assert "drifted" in _read("reviewer.md")
    assert "drifted" not in _read("student.md")


@pytest.mark.unit
def test_the_student_is_told_where_a_wrong_subject_belongs() -> None:
    """Not "stay silent" — "raise it, but the expert owns that call".

    Silencing the learner's instinct would lose signal; routing it correctly keeps it.
    """
    text = _read("student.md")

    assert "expert reviewer owns" in text


@pytest.mark.unit
def test_the_reviser_may_remove_cells_when_the_brief_says_overwhelming() -> None:
    """The verdict is worthless if the agent that receives it cannot act on it.

    reviser.md otherwise says "keep the notebook roughly the same size", which would
    forbid the exact repair an `overwhelming` verdict calls for.
    """
    text = _read("reviser.md")

    assert "overwhelming" in text
    assert "remove cells" in text
