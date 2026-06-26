"""Tests for the agentic CLI subcommand (Phase 9).

Tests verify that `forged agentic` correctly:
1. Parses arguments
2. Invokes run_pipeline()
3. Writes lesson.ipynb and SUMMARY.md
4. Includes routing log in outputs
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.cli import _cmd_agentic
from forged.config import load_pipeline
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@pytest.mark.integration
def test_agentic_cli_runs_pipeline(tmp_path: Path) -> None:
    """forged agentic --brief ... --run-dir ... runs the pipeline."""
    import nbformat

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    for name in ("planner", "code_author", "student", "reviewer", "reviser"):
        (personas_dir / f"{name}.md").write_text(f"Persona for {name}.", encoding="utf-8")

    run_dir = tmp_path / "run"

    def mock_planner(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(Artifact(name=f"lesson_plan_v{state.iteration}", kind="text", content="Plan"))
        output = StageOutput(
            stage=PipelineStage.PLANNER,
            artifact_name=f"lesson_plan_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.CODE_AUTHOR)

    def mock_code_author(state: PipelineState, store: ArtifactStore) -> PipelineState:
        notebook = nbformat.v4.new_notebook()
        notebook.cells = [
            nbformat.v4.new_markdown_cell("# Lesson"),
            nbformat.v4.new_code_cell("print('hello')"),
        ]
        store.put(
            Artifact(
                name=f"lesson_notebook_v{state.iteration}",
                kind="notebook",
                content=nbformat.writes(notebook),
            )
        )
        output = StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name=f"lesson_notebook_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.EXECUTOR)

    def mock_executor(state: PipelineState, store: ArtifactStore) -> PipelineState:
        exec_report = {"ok": True, "failed_cells": [], "error_summary": None}
        store.put(
            Artifact(
                name=f"execution_report_v{state.iteration}",
                kind="json",
                content=json.dumps(exec_report),
            )
        )
        output = StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=f"execution_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.STUDENT)

    def mock_student(state: PipelineState, store: ArtifactStore) -> PipelineState:
        grade = {"quality_score": 90.0, "blockers": [], "findings": []}
        store.put(
            Artifact(
                name=f"student_grade_report_v{state.iteration}",
                kind="json",
                content=json.dumps(grade),
            )
        )
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVIEWER)

    def mock_reviewer(state: PipelineState, store: ArtifactStore) -> PipelineState:
        review = {"reviewed": True, "blockers": [], "findings": []}
        store.put(
            Artifact(
                name=f"reviewer_report_v{state.iteration}",
                kind="json",
                content=json.dumps(review),
            )
        )
        output = StageOutput(
            stage=PipelineStage.REVIEWER,
            artifact_name=f"reviewer_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.reviewer import ReviewerAgent
    from forged.pipeline.agents.student import StudentAgent

    class MockArgs:
        def __init__(self, run_dir_path, personas_path):
            self.topic = "Test lesson brief"
            self.config = str(CONFIG_DIR / "pipeline.review-loop.yaml")
            self.run_dir = run_dir_path
            self.debug = False
            self.personas = personas_path
            self.learner_profile = None
            self.topic_spec = None

    args = MockArgs(run_dir, str(personas_dir))

    with (
        patch.object(PlannerAgent, "run", AsyncMock(side_effect=mock_planner)),
        patch.object(CodeAuthorAgent, "run", AsyncMock(side_effect=mock_code_author)),
        patch.object(ExecutorAgent, "run", AsyncMock(side_effect=mock_executor)),
        patch.object(StudentAgent, "run", AsyncMock(side_effect=mock_student)),
        patch.object(ReviewerAgent, "run", AsyncMock(side_effect=mock_reviewer)),
    ):
        result = _cmd_agentic(args)

    assert result == 0, "CLI should return exit code 0 on success"
    assert (run_dir / "lesson.ipynb").is_file(), "Should write lesson.ipynb"
    assert (run_dir / "SUMMARY.md").is_file(), "Should write SUMMARY.md"
    assert (run_dir / "pipeline.log").is_file(), "Should write pipeline.log"
    # Token-usage report is always emitted (zeroed here — agents are mocked, so
    # no real LLM calls were recorded).
    assert (run_dir / "usage.json").is_file(), "Should write usage.json"
    assert (run_dir / "USAGE.md").is_file(), "Should write USAGE.md"
    # Even with default profile/topic, the shared context block is stored for agents.
    assert (run_dir / "lesson_context.md").is_file(), "Should store lesson_context"
    # Structured topic spec is persisted so the topic-fidelity detector can read
    # the requested capabilities as data (R1, doc 11).
    topic_spec_path = run_dir / "topic_spec.json"
    assert topic_spec_path.is_file(), "Should store topic_spec.json"
    spec = json.loads(topic_spec_path.read_text())
    assert "learning_objectives" in spec and "title" in spec


@pytest.mark.unit
def test_agentic_cli_rejects_missing_learner_profile(tmp_path: Path) -> None:
    """A bad --learner-profile path is caught as usage error (exit 2) before any run."""
    from forged.cli import _cmd_agentic

    class Args:
        topic = "Teach me coroutines"
        config = str(CONFIG_DIR / "pipeline.review-loop.yaml")
        run_dir = tmp_path / "run"
        debug = False
        personas = str(tmp_path / "personas")
        learner_profile = tmp_path / "does-not-exist.yaml"
        topic_spec = None

    assert _cmd_agentic(Args()) == 2


@pytest.mark.integration
def test_agentic_cli_writes_summary_with_routing_log(tmp_path: Path) -> None:
    """SUMMARY.md includes routing log from state."""
    from forged.cli import _write_agentic_summary

    state = create_initial_state()
    from forged.pipeline.state import RoutingDecision

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="Execution failed with NameError",
    )
    state = state.with_routing_decision(decision).with_terminal("Acceptable")

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    _write_agentic_summary(run_dir, state, 10.5)

    summary = (run_dir / "SUMMARY.md").read_text(encoding="utf-8")
    assert "code_quality" in summary
    assert "NameError" in summary
    assert "Acceptable" in summary


@pytest.mark.unit
def test_agentic_summary_surfaces_degradations(tmp_path: Path) -> None:
    """SUMMARY.md includes a Degradations section so fallbacks are never silent."""
    from forged.cli import _write_agentic_summary
    from forged.pipeline.state import Degradation

    state = create_initial_state()
    state = state.with_degradation(
        Degradation(
            stage=PipelineStage.STUDENT,
            kind="grade_failed",
            detail="LLM returned empty content",
        )
    ).with_terminal("Acceptable", ok=True)

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    _write_agentic_summary(run_dir, state, 5.0)

    summary = (run_dir / "SUMMARY.md").read_text(encoding="utf-8")
    assert "Degradations" in summary
    assert "grade_failed" in summary
    assert "empty content" in summary


@pytest.mark.unit
def test_agentic_summary_surfaces_dropped_topic_capability(tmp_path: Path) -> None:
    """SUMMARY.md names any capability the topic requested but the notebook dropped.

    This is the honesty guarantee of R1: a descope must never be silent.
    """
    from forged.cli import _write_agentic_summary
    from forged.pipeline.state import TopicFidelitySignal

    state = create_initial_state().with_topic_fidelity(
        TopicFidelitySignal(
            requested_capabilities=("Set up a local LLM", "Fine-tune the model with LoRA"),
            covered=("Set up a local LLM",),
            missing=("Fine-tune the model with LoRA",),
            source="deterministic",
        )
    ).with_terminal("Acceptable", ok=True)

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    _write_agentic_summary(run_dir, state, 5.0)

    summary = (run_dir / "SUMMARY.md").read_text(encoding="utf-8")
    assert "Topic Fidelity" in summary
    assert "Fine-tune the model with LoRA" in summary


@pytest.mark.unit
def test_agentic_cli_passes_loaded_pipeline_to_runner(tmp_path: Path) -> None:
    """The agentic command loads pipeline config and passes it into run_pipeline()."""
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    for name in ("planner", "code_author", "student", "reviewer", "reviser"):
        (personas_dir / f"{name}.md").write_text(f"Persona for {name}.", encoding="utf-8")

    class Args:
        topic = "Teach me stacks"
        config = str(CONFIG_DIR / "pipeline.review-loop.yaml")
        run_dir = tmp_path / "run"
        debug = False
        personas = str(personas_dir)
        learner_profile = None
        topic_spec = None

    captured = {}

    async def fake_run_pipeline(state, store, pipeline, personas_dir_arg, provision=False):
        captured["pipeline"] = pipeline
        captured["personas_dir"] = personas_dir_arg
        captured["provision"] = provision
        return state.with_terminal("acceptable", ok=True)

    with patch("forged.pipeline.graph.run_pipeline", new=fake_run_pipeline):
        result = _cmd_agentic(Args())

    assert result == 0
    assert captured["pipeline"].name == load_pipeline(Args.config).name
    # Provisioning is ON by default (D1) unless --no-provision is passed.
    assert captured["provision"] is True
    assert Path(captured["personas_dir"]) == personas_dir
