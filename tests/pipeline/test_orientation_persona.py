"""Persona-contract tests for the learner orientation cell (doc 12).

The orientation cell is a pure persona-prose change — the plumbing (planner reads
brief+profile, code author reads the plan) already exists. These tests read the REAL
``personas/*.md`` files and assert the orientation instruction is present, so it cannot
be silently deleted in a future edit. They are the regression backstop doc 12 calls for.

Run from the repo root (as CI does); the personas dir is resolved relative to cwd, the
same convention used by ``tests/test_pipeline.py`` and ``tests/pipeline/test_agents.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PERSONAS = Path("personas")


def _read(name: str) -> str:
    text = (PERSONAS / name).read_text(encoding="utf-8").lower()
    assert text, f"{name} should not be empty"
    return text


@pytest.mark.unit
def test_planner_persona_designates_orientation_deliverable() -> None:
    """The planner must make the learner-facing orientation an explicit deliverable,
    derived from its existing KNOWN/GAP map (doc 12, Phase 1)."""
    persona = _read("planner.md")
    assert "orientation" in persona, "planner must name the orientation deliverable"


@pytest.mark.unit
def test_planner_persona_gates_orientation_on_gaps() -> None:
    """When there are no GAPs the orientation must collapse to a line / be skipped —
    the gate reuses the gap analysis, not a new heuristic (doc 12, Design decision 5)."""
    persona = _read("planner.md")
    # The gate language ties the orientation to the absence of gaps.
    assert any(
        marker in persona for marker in ("no gap", "no gaps", "without a gap")
    ), "planner must gate the orientation on the GAP list being empty"


@pytest.mark.unit
def test_code_author_persona_first_cell_is_learner_orientation() -> None:
    """The code author's first markdown cell must be a learner ORIENTATION (distinct
    from a topic summary), not just a generic overview (doc 12, Phase 2)."""
    persona = _read("code_author.md")
    assert "orientation" in persona, "code author must define the orientation cell"
    assert "roadmap" in persona, "the orientation must carry a plain-language roadmap"


@pytest.mark.unit
def test_code_author_persona_requires_plain_first_jargon_in_brackets() -> None:
    """The roadmap rule is *plain-first, jargon-in-brackets*: a topic term may appear,
    but the plain phrase leads and the real term goes in parentheses (doc 12)."""
    persona = _read("code_author.md")
    assert "parenthes" in persona, (
        "code author must state the plain-first / jargon-in-parentheses rule"
    )


@pytest.mark.unit
def test_code_author_persona_roadmap_has_both_facets() -> None:
    """The roadmap covers BOTH what the notebook does AND what the learner should
    understand afterward (doc 12, Design decision 4)."""
    persona = _read("code_author.md")
    assert "what the notebook does" in persona, "roadmap must say what the notebook does"
    assert "afterward" in persona or "after the lesson" in persona, (
        "roadmap must say what the learner should understand afterward"
    )


@pytest.mark.unit
def test_code_author_persona_surfaces_assumed_and_gap() -> None:
    """The orientation must surface the plan's assumed-known items and the most-unlocking
    GAP up front, not only scaffold gaps inline (doc 12, Phase 2). Pinned to a phrase unique
    to the orientation section so it guards the new content, not pre-existing rule-5 prose."""
    persona = _read("code_author.md")
    assert "what this assumes" in persona, (
        "orientation must have a 'what this assumes / your likely gap' element"
    )
