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
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)


@pytest.mark.integration
def test_agentic_cli_runs_pipeline(tmp_path: Path) -> None:
    """forged agentic --brief ... --run-dir ... runs the pipeline."""
    import nbformat

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    for name in ("planner", "code_author", "student", "reviser"):
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
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent

    class MockArgs:
        def __init__(self, run_dir_path, personas_path):
            self.brief = "Test lesson brief"
            self.run_dir = run_dir_path
            self.debug = False
            self.personas = personas_path

    args = MockArgs(run_dir, str(personas_dir))

    with (
        patch.object(PlannerAgent, "run", AsyncMock(side_effect=mock_planner)),
        patch.object(CodeAuthorAgent, "run", AsyncMock(side_effect=mock_code_author)),
        patch.object(ExecutorAgent, "run", AsyncMock(side_effect=mock_executor)),
        patch.object(StudentAgent, "run", AsyncMock(side_effect=mock_student)),
    ):
        result = _cmd_agentic(args)

    assert result == 0, "CLI should return exit code 0 on success"
    assert (run_dir / "lesson.ipynb").is_file(), "Should write lesson.ipynb"
    assert (run_dir / "SUMMARY.md").is_file(), "Should write SUMMARY.md"
    assert (run_dir / "pipeline.log").is_file(), "Should write pipeline.log"


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
