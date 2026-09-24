"""Trace enrichment: pipeline semantics land on the Langfuse trace payload.

Lane 2 turns call-level generations into steps a localhost dashboard can read as a
reasoning loop. These tests prove the enriched fields (route_taken, quality_score,
goal_fit, lesson_mode) are extracted from state+store and reach the trace metadata —
without a paid run and without ever breaking an LLM call when data is missing.

All offline: no network, no API key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.config import ModelConfig
from forged.llm import LLMTraceContext, _LangfuseTracer
from forged.pipeline.agents import _semantic_enrichment
from forged.pipeline.state import (
    PipelineStage,
    RoutingDecision,
    StageOutput,
    create_initial_state,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


def _grade(quality_score: float, goal_fit: dict | None = None) -> str:
    payload: dict = {"quality_score": quality_score, "blockers": [], "findings": []}
    if goal_fit is not None:
        payload["goal_fit"] = goal_fit
    return json.dumps(payload)


# ── _metadata: the trace-payload builder ────────────────────────────────────────


def test_metadata_omits_semantic_fields_when_not_yet_known() -> None:
    # Arrange: an early-stage context with no verdicts yet.
    tracer = _LangfuseTracer()
    ctx = LLMTraceContext(stage_name="planner", pipeline_kind="agentic", run_id="r1")

    # Act
    metadata = tracer._metadata(ModelConfig(), ctx)

    # Assert: base fields present, semantic keys absent (not null-cluttered).
    assert metadata["stage_name"] == "planner"
    for key in ("route_taken", "quality_score", "goal_fit", "lesson_mode"):
        assert key not in metadata


def test_metadata_includes_semantic_fields_when_present() -> None:
    # Arrange
    tracer = _LangfuseTracer()
    ctx = LLMTraceContext(
        stage_name="reviser",
        pipeline_kind="agentic",
        run_id="r1",
        route_taken="CONTENT_QUALITY",
        quality_score=72.5,
        goal_fit="overwhelming",
        lesson_mode="executable",
    )

    # Act
    metadata = tracer._metadata(ModelConfig(), ctx)

    # Assert
    assert metadata["route_taken"] == "CONTENT_QUALITY"
    assert metadata["quality_score"] == 72.5
    assert metadata["goal_fit"] == "overwhelming"
    assert metadata["lesson_mode"] == "executable"


def test_metadata_none_context_carries_only_provider_and_model() -> None:
    tracer = _LangfuseTracer()
    metadata = tracer._metadata(ModelConfig(), None)
    assert set(metadata) == {"provider", "model"}


# ── _semantic_enrichment: reading state + store ─────────────────────────────────


def test_enrichment_empty_on_fresh_run(store: ArtifactStore) -> None:
    # A run that has produced nothing yet yields all-None enrichment, no raise.
    state = create_initial_state(run_id="r1")
    enrichment = _semantic_enrichment(state, store)
    assert enrichment.route_taken is None
    assert enrichment.quality_score is None
    assert enrichment.goal_fit is None
    assert enrichment.lesson_mode is None


def test_enrichment_reads_route_from_routing_log(store: ArtifactStore) -> None:
    state = create_initial_state(run_id="r1")
    state = state.with_routing_decision(
        RoutingDecision(
            iteration=0,
            from_stage=PipelineStage.REVISER,
            to_stage=PipelineStage.CONTENT_REVISER,
            classification="CONTENT_QUALITY",
            reason="prose unclear",
        )
    )
    assert _semantic_enrichment(state, store).route_taken == "CONTENT_QUALITY"


def test_enrichment_reads_quality_and_goal_fit_from_grade(store: ArtifactStore) -> None:
    # Arrange: a student grade report on the store, registered as a stage output.
    store.put(
        Artifact(
            name="student_grade_report_v0",
            kind="json",
            content=_grade(80.0, {"fit": False, "problems": ["insufficient"], "text": "x"}),
        )
    )
    state = create_initial_state(run_id="r1").with_output(
        StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name="student_grade_report_v0",
            iteration=0,
        )
    )

    # Act
    enrichment = _semantic_enrichment(state, store)

    # Assert
    assert enrichment.quality_score == 80.0
    assert enrichment.goal_fit == "insufficient"


def test_enrichment_prefers_reviewer_goal_fit_over_student(store: ArtifactStore) -> None:
    # The expert Reviewer is the only critic that can say "drifted"; it must win.
    store.put(
        Artifact(
            name="student_grade_report_v0",
            kind="json",
            content=_grade(60.0, {"fit": True, "problems": [], "text": "ok"}),
        )
    )
    store.put(
        Artifact(
            name="reviewer_report_v0",
            kind="json",
            content=json.dumps(
                {"goal_fit": {"fit": False, "problems": ["drifted"], "text": "off topic"}}
            ),
        )
    )
    state = (
        create_initial_state(run_id="r1")
        .with_output(
            StageOutput(
                stage=PipelineStage.STUDENT,
                artifact_name="student_grade_report_v0",
                iteration=0,
            )
        )
        .with_output(
            StageOutput(
                stage=PipelineStage.REVIEWER,
                artifact_name="reviewer_report_v0",
                iteration=0,
            )
        )
    )

    assert _semantic_enrichment(state, store).goal_fit == "drifted"


def test_enrichment_reads_lesson_mode_from_plan(store: ArtifactStore) -> None:
    plan = "# Lesson\n\n```lesson-mode\nconceptual\n```\n\nSome prose."
    store.put(Artifact(name="lesson_plan_v0", kind="text", content=plan))
    state = create_initial_state(run_id="r1").with_output(
        StageOutput(
            stage=PipelineStage.PLANNER,
            artifact_name="lesson_plan_v0",
            iteration=0,
        )
    )
    assert _semantic_enrichment(state, store).lesson_mode == "conceptual"


def test_enrichment_survives_malformed_grade_json(store: ArtifactStore) -> None:
    # Best-effort contract: a corrupt artifact must not raise or poison the trace.
    store.put(
        Artifact(name="student_grade_report_v0", kind="json", content="{not valid json")
    )
    state = create_initial_state(run_id="r1").with_output(
        StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name="student_grade_report_v0",
            iteration=0,
        )
    )
    enrichment = _semantic_enrichment(state, store)
    assert enrichment.quality_score is None
    assert enrichment.goal_fit is None
