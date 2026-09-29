"""Offline regression: the critique digest on the real 2026-08-13 run.

doc 22 Part VI, R6: *rebuild the digest from the existing per-iteration critiques and
check the `PASSWORD` finding survives to the top rather than being lost with its
iteration.* The self-referential `PASSWORD` validator bug (D3) was filed as a low-
severity style nitpick in three separate iterations and never acted on — it is one of
only two root causes still failing the notebook.

The corpus (tests/corpus/doc22-regression-run) carries the real student and reviewer
reports for four iterations. This test rebuilds the digest from them through the
Reviser's *own* finding parser, so it exercises production coercion, not a test-local
copy of it.

Crucially, doc 22 warns (R1's mistake) that a check which cannot fail proves nothing.
So this file also pins the **counterfactual**: the same finding built from only the
last iteration's critique — i.e. today's non-accumulating behaviour — does NOT surface
to the top. That is the state the digest changes, and it is what gives this check teeth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forged.pipeline.agents.reviser import RevisorAgent
from forged.pipeline.digest import build_digest
from forged.pipeline.state import IterationFindings

_CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "doc22-regression-run"
_ITERATIONS = (0, 1, 2, 3)


def _iteration_findings(agent: RevisorAgent, iteration: int) -> IterationFindings:
    """Parse one iteration's student + reviewer findings exactly as the Reviser does."""
    findings = []
    for prefix, source in (
        ("student_grade_report", "student"),
        ("reviewer_report", "reviewer"),
    ):
        path = _CORPUS / f"{prefix}_v{iteration}.json"
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        findings.extend(
            agent._findings_from_json(raw.get("findings", []), default_source=source)
        )
    return IterationFindings(iteration=iteration, findings=tuple(findings))


@pytest.fixture
def corpus_history() -> list[IterationFindings]:
    # No persona is loaded — _findings_from_json is a pure parser, so the default
    # (personas_dir=None) agent is all this needs.
    agent = RevisorAgent()
    return [_iteration_findings(agent, i) for i in _ITERATIONS]


def _is_password_finding(text: str) -> bool:
    return "password" in text.lower()


@pytest.mark.unit
def test_password_root_cause_survives_to_the_top_of_the_accumulated_digest(
    corpus_history: list[IterationFindings],
) -> None:
    digest = build_digest(corpus_history)
    assert not digest.is_empty

    top = digest.entries[0]
    assert _is_password_finding(top.text), (
        "The persistent PASSWORD validator bug must lead the digest; got: " + top.text
    )
    # It leads because it recurred across iterations, not because of its severity —
    # it was filed low every time (D3). Recurrence is the consequence signal.
    assert top.recurrence >= 3
    assert top.severity in ("LOW", "MEDIUM")


@pytest.mark.unit
def test_counterfactual_last_iteration_only_does_not_surface_password(
    corpus_history: list[IterationFindings],
) -> None:
    """The check has teeth: without accumulation the PASSWORD finding is buried.

    Today every agent reads only the last brief. Rebuilding the digest from just the
    final iteration reproduces that, and there the PASSWORD nitpick sits below the
    iteration's blockers — exactly the loss R6 fixes. If accumulation regressed to
    last-only, the test above would start failing, which is the point.
    """
    last_only = build_digest([corpus_history[-1]])
    assert not last_only.is_empty
    assert not _is_password_finding(last_only.entries[0].text)


@pytest.mark.unit
def test_accumulation_recovers_password_that_last_iteration_alone_loses(
    corpus_history: list[IterationFindings],
) -> None:
    """Directly contrast the two: accumulation moves PASSWORD from buried to top."""
    full_top = build_digest(corpus_history).entries[0].text
    last_top = build_digest([corpus_history[-1]]).entries[0].text
    assert _is_password_finding(full_top)
    assert not _is_password_finding(last_top)
