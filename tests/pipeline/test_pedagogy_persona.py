"""Persona-contract tests for two pedagogy fixes (docs/architecture/14).

Pure persona-prose changes — the plumbing already exists. These read the REAL
``personas/*.md`` and assert the new mandates are present so they cannot be
silently deleted:

A. **Code maps & cell briefs** — dense code (config objects, multi-arg calls) must
   be made followable: one plain-words ASCII pipeline map, a short per-cell brief that
   decodes the parameters, and surfacing of any files the code writes.
B. **Readiness verdict** — when the learner's prerequisite gaps are foundational and too
   deep for one honest lesson, the planner must scope down honestly (and declare the
   un-reachable capability as a fidelity gap) rather than cram the topic in shallowly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PERSONAS = Path("personas")


def _read(name: str) -> str:
    text = (PERSONAS / name).read_text(encoding="utf-8").lower()
    assert text, f"{name} should not be empty"
    return text


# ── A. Code maps & cell briefs (code_author + critics) ───────────────────────


@pytest.mark.unit
def test_code_author_requires_ascii_pipeline_map() -> None:
    """A multi-step lesson must include one plain-words ASCII pipeline map."""
    persona = _read("code_author.md")
    assert "pipeline map" in persona, "code author must mandate a pipeline map"
    assert "ascii" in persona, "the map must be specified as ASCII (renders everywhere)"


@pytest.mark.unit
def test_code_author_requires_cell_brief_that_decodes_parameters() -> None:
    """Dense/new-construct cells get a short brief that decodes the parameters."""
    persona = _read("code_author.md")
    assert "brief" in persona, "code author must mandate a per-cell brief"
    assert "decode" in persona, "the brief must decode the call's meaningful parameters"


@pytest.mark.unit
def test_code_author_surfaces_written_files() -> None:
    """Any file the code writes must be named and explained — never discovered by accident."""
    persona = _read("code_author.md")
    assert "what was created" in persona, (
        "code author must surface files the code writes (what was created, where, why)"
    )


@pytest.mark.unit
def test_student_flags_undecoded_dense_cells_and_silent_artifacts() -> None:
    """The student critic enforces the briefs + artifact-surfacing (content scope)."""
    persona = _read("student.md")
    assert "decode" in persona, "student must flag dense cells whose parameters aren't decoded"
    assert "silent artifact" in persona, "student must flag files written but never mentioned"


@pytest.mark.unit
def test_reviewer_checks_parameter_decode_accuracy() -> None:
    """The expert reviewer verifies the parameter explanations are correct, not just present."""
    persona = _read("reviewer.md")
    assert "decoded" in persona, "reviewer must check that parameter decoding is accurate"


# ── B. Readiness verdict (planner) ───────────────────────────────────────────


@pytest.mark.unit
def test_planner_has_readiness_verdict() -> None:
    """The planner must judge whether the topic is beyond the learner's foundation."""
    persona = _read("planner.md")
    assert "readiness verdict" in persona, "planner must make a readiness verdict"
    assert "foundational" in persona, (
        "the verdict must turn on whether the gaps are foundational"
    )


@pytest.mark.unit
def test_planner_readiness_scopes_down_honestly_not_cram() -> None:
    """When gaps are too deep, scope to a teachable beachhead + declare an honest fidelity gap,
    rather than cramming the topic in shallowly."""
    persona = _read("planner.md")
    assert "beachhead" in persona, "must scope to a teachable beachhead"
    assert "requires prerequisites the learner lacks" in persona, (
        "the un-reachable capability must be declared as an honest fidelity gap with the reason"
    )
