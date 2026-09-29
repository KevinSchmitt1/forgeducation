"""Integration: the Reviser accumulates findings, writes the digest, records remake.

Unit coverage for the digest and the remake decision lives in test_digest.py and
test_remake.py. This file checks the *wiring* in RevisorAgent.run — that a real routing
pass records the iteration's findings, persists a critique_digest artifact, and emits a
brief that carries both the accumulated digest and the (recorded) remake decision.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.agents.reviser import RevisorAgent
from forged.pipeline.failure import (
    Classification,
    ExecutionReport,
    FailureCategory,
    GradeReport,
)
from forged.pipeline.remake import RemakeDecision
from forged.pipeline.state import (
    Evidence,
    Location,
    LocationType,
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


def _state_routing_to_code_author(store: ArtifactStore) -> PipelineState:
    """A post-student state whose signals classify as a code failure (→ code author)."""
    state = create_initial_state(run_id="digest-run")
    store.put(Artifact(
        name="execution_report_v0",
        kind="json",
        content=json.dumps({"ok": False, "failed_cells": [4], "error_summary": "IndentationError"}),
    ))
    store.put(Artifact(
        name="student_grade_report_v0",
        kind="json",
        content=json.dumps({
            "quality_score": 55.0,
            "findings": [
                {"source": "student", "severity": "BLOCKER", "scope": "code",
                 "location": {"type": "cell", "cell_index": 4},
                 "text": "Cell 4 raises an IndentationError before the function definition."},
                {"source": "student", "severity": "LOW", "scope": "content",
                 "location": {"type": "cell", "cell_index": 8},
                 "text": "The forbidden PASSWORD regex is case-sensitive and misses "
                         "lowercase leaks."},
            ],
        }),
    ))
    return state.with_output(
        StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name="student_grade_report_v0",
            iteration=0,
        )
    ).with_current_stage(PipelineStage.REVISER)


def _run(agent: RevisorAgent, state: PipelineState, store: ArtifactStore) -> PipelineState:
    # asyncio.run manages its own loop — robust under full-suite ordering, where an
    # earlier async test can leave get_event_loop() with no current loop.
    return asyncio.run(agent.run(state, store))


@pytest.mark.unit
def test_run_records_findings_and_writes_digest_artifact(store: ArtifactStore) -> None:
    agent = RevisorAgent()
    result = _run(agent, _state_routing_to_code_author(store), store)

    # The iteration's findings are recorded for the digest to accumulate over.
    assert len(result.critique_history) == 1
    assert result.critique_history[0].iteration == 0
    assert len(result.critique_history[0].findings) == 2

    # A standalone digest artifact is persisted for this iteration.
    assert store.has("critique_digest_v0")
    assert "Accumulated critique" in store.get("critique_digest_v0").content


@pytest.mark.unit
def test_brief_carries_digest_and_records_repair_by_default(store: ArtifactStore) -> None:
    agent = RevisorAgent()
    _run(agent, _state_routing_to_code_author(store), store)

    brief = store.get("revision_brief_v0").content
    # The remake decision is recorded (never silent); with zero prior repair rounds it
    # is the default repair, not a remake.
    assert "## Remake decision" in brief
    assert "Repair (default)" in brief
    # The accumulated critique rides along in the brief the author reads.
    assert "Accumulated critique" in brief
    assert "PASSWORD" in brief


@pytest.mark.unit
def test_remake_brief_instructs_full_rewrite_and_shows_whole_digest() -> None:
    """When a remake fires, the brief says REMAKE and carries the remake action item."""
    agent = RevisorAgent()
    finding = Evidence(
        source="reviewer", severity="LOW", scope="content",
        location=Location(type=LocationType.GLOBAL),
        text="The forbidden PASSWORD regex is case-sensitive and misses lowercase leaks.",
    )
    grade = GradeReport(quality_score=55.0, findings=[finding])
    classification = Classification(
        category=FailureCategory.CODE_QUALITY, reason="Code failed to run."
    )
    from forged.pipeline.digest import build_digest
    from forged.pipeline.state import IterationFindings

    digest = build_digest([IterationFindings(iteration=i, findings=(finding,)) for i in (1, 2, 3)])
    remake = RemakeDecision(remake=True, reason="patching not converging")

    brief = agent._synthesize_revision_brief(
        ExecutionReport(ok=False, failed_cells=[1]),
        grade,
        classification,
        PipelineStage.CODE_AUTHOR,
        digest=digest,
        remake_decision=remake,
    )

    assert "**REMAKE**" in brief
    assert "Remake the notebook" in brief
    assert "Accumulated critique" in brief
