"""Persona-contract tests for the plan-time verifiability criterion (doc 20, C3).

The 2026-08-13 plan asked the notebook to "commit the files to the repository" and to
"recommend CI integration". The notebook duly ran `git add` against the learner's real
checkout (`fatal: pathspec ... did not match any files`), and the topic-fidelity detector
then reported the same objective as a DROPPED capability — so the honesty machinery was
pressing the pipeline to keep attempting something a notebook cannot do.

The fix is a criterion the planner applies, deliberately **not** a list of banned
operations: the package allow-list showed that enumerating forbidden things is
simultaneously too narrow and too broad (TODO.md; PR #31). These tests assert the
criterion is present and that no such list crept back in.

Same shape and rationale as `test_orientation_persona.py`: read the real personas so the
instruction cannot be silently deleted in a future edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PERSONAS = Path("personas")
PLANNERS = ("planner.md", "curriculum_planner.md")


def _read(name: str) -> str:
    """Lowercased with whitespace collapsed.

    Persona prose is hard-wrapped, so a phrase this file asserts on routinely spans a
    line break (and picks up a `> ` blockquote marker). Normalizing means these tests
    check the instruction, not the paragraph's current line breaks.
    """
    raw = (PERSONAS / name).read_text(encoding="utf-8")
    assert raw.strip(), f"{name} should not be empty"
    return " ".join(raw.replace(">", " ").lower().split())


@pytest.mark.unit
@pytest.mark.parametrize("persona", PLANNERS)
def test_planner_asks_whether_a_cell_can_verify_the_objective(persona: str) -> None:
    text = _read(persona)

    assert "verifiable inside" in text
    assert "show the learner it worked" in text
    assert "only what the notebook itself creates" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", PLANNERS)
def test_the_criterion_is_illustrated_by_both_sides_of_the_same_verb(persona: str) -> None:
    """Committing is fine in a repo the notebook made, and not fine in the learner's.

    Illustrating both sides is what stops the criterion being read as "never use git".
    """
    text = _read(persona)

    assert "demo repository" in text
    assert "learner's own repository" in text or "commit the files to the repository" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", PLANNERS)
def test_unverifiable_objectives_are_redirected_to_prose_not_deleted(persona: str) -> None:
    """The learner still hears about the next step — it just stops being a claim."""
    text = _read(persona)

    assert "prose" in text
    assert "next step" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", PLANNERS)
def test_the_criterion_is_a_question_not_a_blacklist(persona: str) -> None:
    """Guards the decision recorded in doc 20.

    A list is too narrow (the next un-runnable objective is not on it) and too broad (a
    lesson about git legitimately runs git in a scratch repo). If a future edit turns this
    into an enumeration of banned verbs, this test should be the thing that objects.
    """
    text = _read(persona)

    assert "not a list of banned operations" in text
    for forbidden_framing in ("do not use git", "never run git", "forbidden commands"):
        assert forbidden_framing not in text
