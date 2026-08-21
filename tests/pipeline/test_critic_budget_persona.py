"""Persona-contract tests for the critics' finding budget (doc 22, D2/R2).

Iteration v2 of the 2026-08-13 artifact run filed five findings, three of which were
BLOCKERs restating "cells 12, 17, 20 failed" — which the executor had already
established deterministically, for free, before any grader ran. Only the first five
findings reach the revision brief, so a restatement does not merely waste grader
tokens: it evicts a real judgement from the brief the next agent reads.

Nothing about routing depends on the critics reporting execution failures. When the
notebook does not run, `classify()` returns CODE_QUALITY from the ExecutionReport at
priority 2, before any finding is consulted (`forged/pipeline/failure.py`), and the
brief carries the failed-cell list and error summary itself
(`RevisorAgent._synthesize_revision_brief`). So this instruction removes duplication,
not signal.

Same shape and rationale as `test_verifiability_persona.py`: read the real personas so
the instruction cannot be silently deleted in a future edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PERSONAS = Path("personas")
CRITICS = ("student.md", "reviewer.md")


def _read(name: str) -> str:
    """Lowercased with whitespace collapsed.

    Persona prose is hard-wrapped, so a phrase this file asserts on routinely spans a
    line break. Normalizing means these tests check the instruction, not the
    paragraph's current line breaks.
    """
    raw = (PERSONAS / name).read_text(encoding="utf-8")
    assert raw.strip(), f"{name} should not be empty"
    return " ".join(raw.replace(">", " ").lower().split())


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_is_told_not_to_restate_the_execution_report(persona: str) -> None:
    """The core R2 instruction: a finding that only repeats "cell N failed" is waste."""
    text = _read(persona)

    assert "already knows" in text
    assert "restat" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_is_told_the_brief_already_carries_the_failed_cells(persona: str) -> None:
    """The critic must know *why* restating is redundant, not just that it is banned.

    An instruction whose reason is withheld gets overridden by the model's own
    judgement the first time a failure looks important enough to mention twice.
    """
    text = _read(persona)

    assert "revision brief" in text
    assert "failed cell" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_is_told_what_to_file_instead(persona: str) -> None:
    """The budget is redirected, not just cut.

    v3's best finding named the mechanism — a nested triple-quoted docstring closing
    the outer literal — which no execution report could have produced. That is the
    shape the freed budget is for.
    """
    text = _read(persona)

    assert "mechanism" in text


@pytest.mark.unit
@pytest.mark.parametrize("persona", CRITICS)
def test_critic_is_told_not_to_suppress_a_real_finding(persona: str) -> None:
    """Guard against over-correction: silence is not the goal.

    "Do not restate the execution report" read too broadly becomes "do not report
    code problems", which would blind the loop to the very failures it must fix.
    """
    text = _read(persona)

    assert "do not stay silent" in text


@pytest.mark.unit
def test_student_is_told_a_stopped_run_cannot_score_well_on_correctness() -> None:
    """R2 hands the judgement to the rubric, so `correctness` must absorb it.

    This is the dimension the doc-22 R1 fatal gate reads
    (`forged/pipeline/failure.py`), so a run the learner could not complete has to
    land there rather than in a restated finding. The floor's numeric value is
    deliberately NOT named in the persona: telling a grader the exact cut-off
    invites it to score just above the line.
    """
    text = _read("student.md")

    assert "could not complete" in text
    assert "75" not in text
