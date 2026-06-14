"""Phase 6: LangGraph integration tests.

Tests cover graph compilation, node membership, edge structure, conditional
routing, full pipeline execution (with mocked agents), state evolution, error
handling, and determinism.

All LLM interactions remain mocked — no real API calls are made.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.config import PipelineConfig, load_pipeline
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    RoutingDecision,
    StageOutput,
    create_initial_state,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    """Temporary personas directory with all required persona files."""
    d = tmp_path / "personas"
    d.mkdir()
    for name in ("planner", "code_author", "student", "reviser"):
        (d / f"{name}.md").write_text(f"Persona for {name}.", encoding="utf-8")
    return d


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    """In-memory ArtifactStore backed by a temp directory."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


@pytest.fixture
def pipeline_config() -> PipelineConfig:
    config_path = Path(__file__).resolve().parents[2] / "config" / "pipeline.review-loop.yaml"
    return load_pipeline(config_path)


@pytest.fixture
def initial_state() -> PipelineState:
    """Fresh pipeline state at iteration 0, stage PLANNER."""
    return create_initial_state(run_id="test-graph-001")


# ── Graph compilation tests ────────────────────────────────────────────────────


@pytest.mark.integration
def test_graph_compiles(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """build_pipeline_graph() returns a compiled graph that can be invoked."""
    from forged.pipeline.graph import build_pipeline_graph

    graph = build_pipeline_graph(
        store=artifact_store, pipeline=pipeline_config, personas_dir=personas_dir
    )
    assert graph is not None


@pytest.mark.integration
def test_graph_has_all_nodes(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """The compiled graph contains exactly the five required nodes."""
    from forged.pipeline.graph import build_pipeline_graph

    graph = build_pipeline_graph(
        store=artifact_store, pipeline=pipeline_config, personas_dir=personas_dir
    )
    node_names = set(graph.get_graph().nodes.keys())
    required = {"planner", "code_author", "executor", "student", "revisor"}
    assert required.issubset(node_names)


@pytest.mark.integration
def test_graph_has_start_edge(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """The compiled graph has an edge from __start__ to planner."""
    from forged.pipeline.graph import build_pipeline_graph

    graph = build_pipeline_graph(
        store=artifact_store, pipeline=pipeline_config, personas_dir=personas_dir
    )
    edges = graph.get_graph().edges
    source_target_pairs = {(e.source, e.target) for e in edges}
    assert ("__start__", "planner") in source_target_pairs


@pytest.mark.integration
def test_graph_has_linear_edges(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """The linear edges planner→code_author→executor→student→revisor all exist."""
    from forged.pipeline.graph import build_pipeline_graph

    graph = build_pipeline_graph(
        store=artifact_store, pipeline=pipeline_config, personas_dir=personas_dir
    )
    edges = graph.get_graph().edges
    source_target_pairs = {(e.source, e.target) for e in edges}
    linear_edges = [
        ("planner", "code_author"),
        ("code_author", "executor"),
        ("executor", "student"),
        ("student", "revisor"),
    ]
    for src, tgt in linear_edges:
        assert (src, tgt) in source_target_pairs, f"Missing edge: {src} → {tgt}"


@pytest.mark.unit
def test_graph_uses_stage_specific_models(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """Graph construction resolves planner/code_author/student models by stage name."""
    from forged.pipeline.graph import build_pipeline_graph

    captured_models: list[str] = []

    class FakeLLMClient:
        def __init__(self, config):
            captured_models.append(config.model)

    with patch("forged.pipeline.graph.LLMClient", FakeLLMClient):
        build_pipeline_graph(store=artifact_store, pipeline=pipeline_config, personas_dir=personas_dir)

    assert captured_models == ["gpt-5-mini", "gpt-5", "gpt-5-mini"]


# ── Routing logic tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_revisor_routes_to_planner_on_blocker_structure() -> None:
    """revisor_route() returns 'planner' when last routing decision targets PLANNER."""
    from forged.pipeline.graph import revisor_route

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.PLANNER,
        classification="blocker_structure",
        reason="Lesson structure has a blocker-level issue.",
    )
    state = create_initial_state()
    state = state.with_routing_decision(decision)

    result = revisor_route(state)
    assert result == "planner"


@pytest.mark.unit
def test_revisor_routes_to_code_author_on_code_quality() -> None:
    """revisor_route() returns 'code_author' when last routing decision targets CODE_AUTHOR."""
    from forged.pipeline.graph import revisor_route

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="Code failed to run.",
    )
    state = create_initial_state()
    state = state.with_routing_decision(decision)

    result = revisor_route(state)
    assert result == "code_author"


@pytest.mark.unit
def test_revisor_routes_to_reviser_on_content_quality() -> None:
    """revisor_route() returns 'reviser' when last routing decision targets REVISER."""
    from forged.pipeline.graph import revisor_route

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.REVISER,
        classification="content_quality",
        reason="Content needs revision.",
    )
    state = create_initial_state()
    state = state.with_routing_decision(decision)

    result = revisor_route(state)
    assert result == "reviser"


@pytest.mark.unit
def test_revisor_terminates_on_acceptable() -> None:
    """revisor_route() returns END when state is_terminal (ACCEPTABLE path)."""
    from langgraph.graph import END

    from forged.pipeline.graph import revisor_route

    state = create_initial_state()
    state = state.with_terminal("Notebook is acceptable.")

    result = revisor_route(state)
    assert result == END


@pytest.mark.unit
def test_revisor_terminates_on_unclassifiable() -> None:
    """revisor_route() returns END when state is_terminal (UNCLASSIFIABLE path)."""
    from langgraph.graph import END

    from forged.pipeline.graph import revisor_route

    state = create_initial_state()
    state = state.with_terminal("Unable to classify the issue. Manual review required.")

    result = revisor_route(state)
    assert result == END


@pytest.mark.unit
def test_revisor_terminates_when_no_routing_log() -> None:
    """revisor_route() returns END when routing_log is empty."""
    from langgraph.graph import END

    from forged.pipeline.graph import revisor_route

    state = create_initial_state()
    result = revisor_route(state)
    assert result == END


@pytest.mark.unit
def test_revisor_terminates_when_to_stage_is_none() -> None:
    """revisor_route() returns END when last decision has to_stage=None."""
    from langgraph.graph import END

    from forged.pipeline.graph import revisor_route

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=None,
        classification="acceptable",
        reason="Acceptable.",
    )
    state = create_initial_state()
    state = state.with_routing_decision(decision)

    result = revisor_route(state)
    assert result == END


# ── Full pipeline execution tests (all agents mocked) ─────────────────────────


def _build_acceptable_agents(
    personas_dir: Path, artifact_store: ArtifactStore
) -> dict[str, Any]:
    """Return mock agent objects whose run() methods simulate a successful run."""
    exec_report = json.dumps({"ok": True, "failed_cells": [], "error_summary": None})
    grade_report = json.dumps({"quality_score": 92.0, "blockers": [], "findings": []})

    def make_planner_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(Artifact(name=f"lesson_plan_v{state.iteration}", kind="text", content="Plan"))
        output = StageOutput(
            stage=PipelineStage.PLANNER,
            artifact_name=f"lesson_plan_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.CODE_AUTHOR)

    def make_code_author_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(
            Artifact(name=f"lesson_notebook_v{state.iteration}", kind="notebook", content="[]")
        )
        output = StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name=f"lesson_notebook_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.EXECUTOR)

    def make_executor_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(
            Artifact(name=f"execution_report_v{state.iteration}", kind="json", content=exec_report)
        )
        output = StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=f"execution_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.STUDENT)

    def make_student_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(
            Artifact(
                name=f"student_grade_report_v{state.iteration}", kind="json", content=grade_report
            )
        )
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    return {
        "planner_run": AsyncMock(side_effect=make_planner_run),
        "code_author_run": AsyncMock(side_effect=make_code_author_run),
        "executor_run": AsyncMock(side_effect=make_executor_run),
        "student_run": AsyncMock(side_effect=make_student_run),
    }


@pytest.mark.integration
def test_full_pipeline_acceptable_path(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """Full pipeline runs planner→code_author→executor→student→revisor→END on ACCEPTABLE."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    mocks = _build_acceptable_agents(personas_dir, artifact_store)

    with (
        patch.object(PlannerAgent, "run", mocks["planner_run"]),
        patch.object(CodeAuthorAgent, "run", mocks["code_author_run"]),
        patch.object(ExecutorAgent, "run", mocks["executor_run"]),
        patch.object(StudentAgent, "run", mocks["student_run"]),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)
    assert final_state.is_terminal
    assert "acceptable" in (final_state.terminal_reason or "").lower()


@pytest.mark.integration
def test_full_pipeline_with_one_reroute(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """Pipeline routes CODE_QUALITY back to code_author once then terminates ACCEPTABLE."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    call_count = {"executor": 0}

    def executor_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        call_count["executor"] += 1
        ok = call_count["executor"] > 1
        report = json.dumps(
            {
                "ok": ok,
                "failed_cells": [] if ok else [1],
                "error_summary": None if ok else "NameError",
            }
        )
        store.put(
            Artifact(name=f"execution_report_v{state.iteration}", kind="json", content=report)
        )
        output = StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=f"execution_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.STUDENT)

    good_grade = json.dumps({"quality_score": 90.0, "blockers": [], "findings": []})

    def student_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(
            Artifact(
                name=f"student_grade_report_v{state.iteration}", kind="json", content=good_grade
            )
        )
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    mocks = _build_acceptable_agents(personas_dir, artifact_store)
    mocks["executor_run"] = AsyncMock(side_effect=executor_run)
    mocks["student_run"] = AsyncMock(side_effect=student_run)

    with (
        patch.object(PlannerAgent, "run", mocks["planner_run"]),
        patch.object(CodeAuthorAgent, "run", mocks["code_author_run"]),
        patch.object(ExecutorAgent, "run", mocks["executor_run"]),
        patch.object(StudentAgent, "run", mocks["student_run"]),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)
    assert final_state.is_terminal
    assert call_count["executor"] == 2


@pytest.mark.integration
def test_full_pipeline_respects_budget(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """Pipeline terminates when code_author budget is exhausted.

    Simulates a state where code_author has already been attempted once
    (budget=1) and the next reviser call sees the budget is exhausted.
    """
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline
    from forged.pipeline.router import Router, RoutingBudget

    failing_report = json.dumps({"ok": False, "failed_cells": [1], "error_summary": "Error"})
    grade = json.dumps({"quality_score": 50.0, "blockers": [], "findings": []})

    def executor_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(
            Artifact(
                name=f"execution_report_v{state.iteration}", kind="json", content=failing_report
            )
        )
        output = StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=f"execution_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.STUDENT)

    def student_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(
            Artifact(name=f"student_grade_report_v{state.iteration}", kind="json", content=grade)
        )
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    mocks = _build_acceptable_agents(personas_dir, artifact_store)
    mocks["executor_run"] = AsyncMock(side_effect=executor_run)
    mocks["student_run"] = AsyncMock(side_effect=student_run)

    tight_budget = RoutingBudget(code_author=1)

    def make_tight_router(budget=None):
        return Router(budget=tight_budget)

    # State with code_author already attempted once — budget will be exhausted on next reviser call
    budget_state = create_initial_state(run_id="test-budget-002")
    budget_state = budget_state.with_attempt(PipelineStage.CODE_AUTHOR)

    with (
        patch.object(PlannerAgent, "run", mocks["planner_run"]),
        patch.object(CodeAuthorAgent, "run", mocks["code_author_run"]),
        patch.object(ExecutorAgent, "run", mocks["executor_run"]),
        patch.object(StudentAgent, "run", mocks["student_run"]),
        patch("forged.pipeline.agents.reviser.Router", make_tight_router),
    ):
        final_state = asyncio.run(
            run_pipeline(budget_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)
    assert final_state.is_terminal


# ── State evolution tests ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_initial_state_current_stage_is_planner() -> None:
    """create_initial_state() starts at PipelineStage.PLANNER."""
    state = create_initial_state()
    assert state.current_stage == PipelineStage.PLANNER


@pytest.mark.unit
def test_state_iteration_increments() -> None:
    """Routing decisions increment the iteration counter."""
    state = create_initial_state()
    assert state.iteration == 0

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.CODE_AUTHOR,
        classification="code_quality",
        reason="Code failed.",
    )
    state = state.with_routing_decision(decision)
    assert state.iteration == 1


@pytest.mark.unit
def test_state_outputs_accumulate() -> None:
    """Each with_output() call appends to the outputs list without mutation."""
    state = create_initial_state()
    assert len(state.outputs) == 0

    output1 = StageOutput(stage=PipelineStage.PLANNER, artifact_name="plan_v0", iteration=0)
    state = state.with_output(output1)
    assert len(state.outputs) == 1

    output2 = StageOutput(stage=PipelineStage.CODE_AUTHOR, artifact_name="notebook_v0", iteration=0)
    state = state.with_output(output2)
    assert len(state.outputs) == 2
    assert state.outputs[0].stage == PipelineStage.PLANNER
    assert state.outputs[1].stage == PipelineStage.CODE_AUTHOR


@pytest.mark.unit
def test_state_stage_attempts_tracked() -> None:
    """with_attempt() increments stage_attempts correctly across multiple stages."""
    state = create_initial_state()

    state = state.with_attempt(PipelineStage.CODE_AUTHOR)
    state = state.with_attempt(PipelineStage.CODE_AUTHOR)
    state = state.with_attempt(PipelineStage.PLANNER)

    assert state.get_stage_attempt_count(PipelineStage.CODE_AUTHOR) == 2
    assert state.get_stage_attempt_count(PipelineStage.PLANNER) == 1
    assert state.get_stage_attempt_count(PipelineStage.EXECUTOR) == 0


# ── Error handling tests ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_graph_handles_agent_error(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """If planner returns a terminal state, pipeline terminates gracefully."""
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.graph import run_pipeline

    async def failing_planner(state: PipelineState, store: ArtifactStore) -> PipelineState:
        return state.with_terminal("Agent error: unexpected exception")

    with patch.object(PlannerAgent, "run", AsyncMock(side_effect=failing_planner)):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)
    assert final_state.is_terminal


@pytest.mark.integration
def test_graph_handles_missing_artifact(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """Reviser with no artifacts in store at all terminates gracefully (UNCLASSIFIABLE)."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    def student_run_no_artifacts(state: PipelineState, store: ArtifactStore) -> PipelineState:
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    def executor_run_no_artifact(state: PipelineState, store: ArtifactStore) -> PipelineState:
        output = StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=f"execution_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.STUDENT)

    mocks = _build_acceptable_agents(personas_dir, artifact_store)
    mocks["executor_run"] = AsyncMock(side_effect=executor_run_no_artifact)
    mocks["student_run"] = AsyncMock(side_effect=student_run_no_artifacts)

    with (
        patch.object(PlannerAgent, "run", mocks["planner_run"]),
        patch.object(CodeAuthorAgent, "run", mocks["code_author_run"]),
        patch.object(ExecutorAgent, "run", mocks["executor_run"]),
        patch.object(StudentAgent, "run", mocks["student_run"]),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)
    assert final_state.is_terminal


# ── Phase 7: Real Executor integration tests ───────────────────────────────────


@pytest.mark.integration
def test_reviser_writes_revision_brief(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """Reviser writes revision_brief artifact containing failure context for rerouted agents.

    This test verifies Phase 8: when the reviser reroutes to an agent,
    it writes a revision_brief with execution/grade context.
    """
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    call_count = {"code_author": 0}

    def planner_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(Artifact(name=f"lesson_plan_v{state.iteration}", kind="text", content="Plan"))
        output = StageOutput(
            stage=PipelineStage.PLANNER,
            artifact_name=f"lesson_plan_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.CODE_AUTHOR)

    def code_author_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        import nbformat

        call_count["code_author"] += 1
        notebook = nbformat.v4.new_notebook()
        source_code = (
            "print('hello')" if call_count["code_author"] > 1 else "undefined_variable_that_fails"
        )
        notebook.cells = [
            nbformat.v4.new_markdown_cell("# Test"),
            nbformat.v4.new_code_cell(source_code),
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

    def student_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        grade_report = json.dumps({"quality_score": 90.0, "blockers": [], "findings": []})
        store.put(
            Artifact(
                name=f"student_grade_report_v{state.iteration}", kind="json", content=grade_report
            )
        )
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    with (
        patch.object(PlannerAgent, "run", AsyncMock(side_effect=planner_run)),
        patch.object(CodeAuthorAgent, "run", AsyncMock(side_effect=code_author_run)),
        patch.object(StudentAgent, "run", AsyncMock(side_effect=student_run)),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert final_state.is_terminal, "Pipeline should terminate"
    assert call_count["code_author"] >= 2, "CodeAuthor should have been called twice"
    assert artifact_store.has(
        "revision_brief_v0"
    ), "Reviser should have written revision_brief_v0 on reroute"
    brief_content = artifact_store.get("revision_brief_v0").content
    assert "code_quality" in brief_content.lower() or "classification" in brief_content.lower()


@pytest.mark.integration
def test_real_executor_detects_code_quality_failure(
    personas_dir: Path, artifact_store: ArtifactStore, pipeline_config: PipelineConfig
) -> None:
    """Real executor detects a failing notebook; classified CODE_QUALITY, routed to CodeAuthor.

    This test verifies Phase 7: the real ExecutorStage correctly identifies
    execution failures, leading to CODE_QUALITY classification and rerouting.
    """
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    call_count = {"code_author": 0}

    def planner_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        store.put(Artifact(name=f"lesson_plan_v{state.iteration}", kind="text", content="Plan"))
        output = StageOutput(
            stage=PipelineStage.PLANNER,
            artifact_name=f"lesson_plan_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.CODE_AUTHOR)

    def code_author_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        import nbformat

        call_count["code_author"] += 1
        notebook = nbformat.v4.new_notebook()
        source_code = (
            "print('hello')" if call_count["code_author"] > 1 else "undefined_variable_that_fails"
        )
        notebook.cells = [
            nbformat.v4.new_markdown_cell("# Test Lesson"),
            nbformat.v4.new_code_cell(source_code),
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

    def student_run(state: PipelineState, store: ArtifactStore) -> PipelineState:
        grade_report = json.dumps({"quality_score": 90.0, "blockers": [], "findings": []})
        store.put(
            Artifact(
                name=f"student_grade_report_v{state.iteration}", kind="json", content=grade_report
            )
        )
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=f"student_grade_report_v{state.iteration}",
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    initial_state = create_initial_state(run_id="test-real-executor")

    with (
        patch.object(PlannerAgent, "run", AsyncMock(side_effect=planner_run)),
        patch.object(CodeAuthorAgent, "run", AsyncMock(side_effect=code_author_run)),
        patch.object(StudentAgent, "run", AsyncMock(side_effect=student_run)),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)
    assert final_state.is_terminal, (
        "Pipeline should terminate (accept second attempt or hit budget)"
    )
    assert call_count["code_author"] >= 2, (
        "CodeAuthor should have been called at least twice (initial + reroute)"
    )


# ── Determinism tests ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_same_input_produces_same_route() -> None:
    """Identical state + same routing decision → same revisor_route() output every time."""
    from forged.pipeline.graph import revisor_route

    decision = RoutingDecision(
        iteration=0,
        from_stage=PipelineStage.REVISER,
        to_stage=PipelineStage.PLANNER,
        classification="blocker_structure",
        reason="Plan is wrong.",
    )
    state = create_initial_state()
    state = state.with_routing_decision(decision)

    results = [revisor_route(state) for _ in range(10)]
    assert len(set(results)) == 1, "revisor_route() must be deterministic"
    assert results[0] == "planner"


@pytest.mark.unit
def test_revisor_route_is_deterministic_for_terminal() -> None:
    """revisor_route() always returns END for a terminal state, every time."""
    from langgraph.graph import END

    from forged.pipeline.graph import revisor_route

    state = create_initial_state().with_terminal("Budget exhausted.")

    results = [revisor_route(state) for _ in range(10)]
    assert all(r == END for r in results)


# ── run_pipeline function tests ────────────────────────────────────────────────


@pytest.mark.integration
def test_run_pipeline_returns_pipeline_state(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """run_pipeline() returns a PipelineState after execution completes."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    mocks = _build_acceptable_agents(personas_dir, artifact_store)

    with (
        patch.object(PlannerAgent, "run", mocks["planner_run"]),
        patch.object(CodeAuthorAgent, "run", mocks["code_author_run"]),
        patch.object(ExecutorAgent, "run", mocks["executor_run"]),
        patch.object(StudentAgent, "run", mocks["student_run"]),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert isinstance(final_state, PipelineState)


@pytest.mark.integration
def test_run_pipeline_terminal_state_has_reason(
    personas_dir: Path,
    artifact_store: ArtifactStore,
    initial_state: PipelineState,
    pipeline_config: PipelineConfig,
) -> None:
    """run_pipeline() returns a terminal state with a non-None terminal_reason."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.student import StudentAgent
    from forged.pipeline.graph import run_pipeline

    mocks = _build_acceptable_agents(personas_dir, artifact_store)

    with (
        patch.object(PlannerAgent, "run", mocks["planner_run"]),
        patch.object(CodeAuthorAgent, "run", mocks["code_author_run"]),
        patch.object(ExecutorAgent, "run", mocks["executor_run"]),
        patch.object(StudentAgent, "run", mocks["student_run"]),
    ):
        final_state = asyncio.run(
            run_pipeline(initial_state, artifact_store, pipeline_config, personas_dir)
        )

    assert final_state.terminal_reason is not None
    assert len(final_state.terminal_reason) > 0
