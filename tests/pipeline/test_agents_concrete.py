"""Concrete agent tests for Phase 5 — all five agents.

Tests cover persona loading, next_stage(), run() state transitions,
artifact production, immutability, and reviser routing integration.
All run() methods are mocked at the LLM layer — no real API calls.

TDD: tests written FIRST (RED phase) before implementation exists.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    """Temporary personas directory populated with all required persona files."""
    d = tmp_path / "personas"
    d.mkdir()
    (d / "planner.md").write_text(
        "You are the Lesson Planner. Plan lessons for learners.", encoding="utf-8"
    )
    (d / "code_author.md").write_text(
        "You are the Code Author. Write notebook code cells.", encoding="utf-8"
    )
    (d / "student.md").write_text(
        "You are the Student. Review the notebook as a learner.", encoding="utf-8"
    )
    (d / "reviewer.md").write_text(
        "You are the Reviewer. Judge correctness and teaching quality.", encoding="utf-8"
    )
    (d / "reviser.md").write_text(
        "You are the Reviser. Improve notebook quality.", encoding="utf-8"
    )
    return d


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    """In-memory-backed ArtifactStore writing to a temp run directory."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


@pytest.fixture
def initial_state() -> PipelineState:
    """Fresh pipeline state at iteration 0, stage PLANNER."""
    return create_initial_state(run_id="test-run-001")


@pytest.fixture
def stub_llm_client():
    """Offline LLM client returning a canned plan, so run() needs no API key.

    PlannerAgent re-raises on LLM failure (unlike CodeAuthor/Student, which
    degrade to fallbacks), so its run() tests must inject a client rather than
    reach the network — these are unit tests, not live API calls.
    """

    class _StubClient:
        def complete(self, system_prompt: str, user_prompt: str, trace_context=None) -> str:
            return "# Lesson Plan\n\n## Objectives\n- Understand the topic"

    return _StubClient()


@pytest.fixture
def state_with_plan(artifact_store: ArtifactStore) -> PipelineState:
    """Pipeline state after planner ran — has a lesson_plan artifact."""
    state = create_initial_state(run_id="test-run-002")
    artifact_store.put(
        Artifact(
            name="lesson_plan_v0",
            kind="text",
            content="# Lesson: Hash Maps\n\n## Objectives\n- Understand hash maps",
        )
    )
    return state.with_output(
        StageOutput(stage=PipelineStage.PLANNER, artifact_name="lesson_plan_v0", iteration=0)
    ).with_current_stage(PipelineStage.CODE_AUTHOR)


@pytest.fixture
def state_with_notebook(artifact_store: ArtifactStore) -> PipelineState:
    """Pipeline state after code author ran — has a lesson_notebook artifact."""
    import nbformat

    state = create_initial_state(run_id="test-run-003")
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell("# Hash Maps\n\nIntroduction to hash maps."),
        nbformat.v4.new_code_cell("data = {'key': 'value'}\nprint(data)"),
    ]
    artifact_store.put(
        Artifact(
            name="lesson_notebook_v0",
            kind="notebook",
            content=nbformat.writes(notebook),
        )
    )
    return state.with_output(
        StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name="lesson_notebook_v0",
            iteration=0,
        )
    ).with_current_stage(PipelineStage.EXECUTOR)


@pytest.fixture
def state_with_execution(artifact_store: ArtifactStore) -> PipelineState:
    """Pipeline state after executor ran — has execution_report artifact."""
    import nbformat

    state = create_initial_state(run_id="test-run-004")
    exec_report = {"ok": True, "failed_cells": [], "error_summary": None}
    artifact_store.put(
        Artifact(
            name="execution_report_v0",
            kind="json",
            content=json.dumps(exec_report),
        )
    )
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell("# Hash Maps"),
        nbformat.v4.new_code_cell("print('hello')"),
    ]
    artifact_store.put(
        Artifact(name="lesson_notebook_v0", kind="notebook", content=nbformat.writes(notebook))
    )
    return state.with_output(
        StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name="execution_report_v0",
            iteration=0,
        )
    ).with_current_stage(PipelineStage.STUDENT)


@pytest.fixture
def state_with_failing_notebook(artifact_store: ArtifactStore) -> PipelineState:
    """Pipeline state after code author ran — has a notebook with intentionally failing cell."""
    import nbformat

    state = create_initial_state(run_id="test-run-006")
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell("# Failing Notebook"),
        nbformat.v4.new_code_cell("undefined_variable_that_will_fail"),
    ]
    artifact_store.put(
        Artifact(
            name="lesson_notebook_v0",
            kind="notebook",
            content=nbformat.writes(notebook),
        )
    )
    return state.with_output(
        StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name="lesson_notebook_v0",
            iteration=0,
        )
    ).with_current_stage(PipelineStage.EXECUTOR)


@pytest.fixture
def state_with_grade(artifact_store: ArtifactStore) -> PipelineState:
    """Pipeline state after student ran — has grade_report and execution_report artifacts."""
    state = create_initial_state(run_id="test-run-005")
    exec_report = {"ok": True, "failed_cells": [], "error_summary": None}
    grade_report = {
        "quality_score": 90.0,
        "blockers": [],
        "findings": [],
    }
    artifact_store.put(
        Artifact(
            name="execution_report_v0",
            kind="json",
            content=json.dumps(exec_report),
        )
    )
    artifact_store.put(
        Artifact(
            name="student_grade_report_v0",
            kind="json",
            content=json.dumps(grade_report),
        )
    )
    return state.with_output(
        StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name="student_grade_report_v0",
            iteration=0,
        )
    ).with_current_stage(PipelineStage.REVISER)


# ── PlannerAgent tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_planner_agent_loads_planner_persona(personas_dir: Path) -> None:
    """PlannerAgent._load_persona() returns the planner.md content as a str."""
    from forged.pipeline.agents.planner import PlannerAgent

    agent = PlannerAgent(personas_dir=personas_dir)
    assert isinstance(agent.persona, str)
    assert "Lesson Planner" in agent.persona


@pytest.mark.unit
def test_planner_agent_next_stage(personas_dir: Path) -> None:
    """PlannerAgent.next_stage() returns PipelineStage.CODE_AUTHOR."""
    from forged.pipeline.agents.planner import PlannerAgent

    agent = PlannerAgent(personas_dir=personas_dir)
    assert agent.next_stage() == PipelineStage.CODE_AUTHOR


@pytest.mark.unit
def test_planner_agent_run_updates_stage(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    stub_llm_client,
) -> None:
    """PlannerAgent.run() returns a state with current_stage=CODE_AUTHOR."""
    from forged.pipeline.agents.planner import PlannerAgent

    agent = PlannerAgent(personas_dir=personas_dir, llm_client=stub_llm_client)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(initial_state, artifact_store)
    )
    assert result.current_stage == PipelineStage.CODE_AUTHOR


@pytest.mark.unit
def test_planner_agent_run_adds_output(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    stub_llm_client,
) -> None:
    """PlannerAgent.run() returns a state with outputs list increased by 1."""
    from forged.pipeline.agents.planner import PlannerAgent

    agent = PlannerAgent(personas_dir=personas_dir, llm_client=stub_llm_client)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(initial_state, artifact_store)
    )
    assert len(result.outputs) == len(initial_state.outputs) + 1


@pytest.mark.unit
def test_planner_agent_run_is_immutable(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    stub_llm_client,
) -> None:
    """PlannerAgent.run() never mutates the input state."""
    from forged.pipeline.agents.planner import PlannerAgent

    original_stage = initial_state.current_stage
    original_outputs_count = len(initial_state.outputs)
    agent = PlannerAgent(personas_dir=personas_dir, llm_client=stub_llm_client)
    asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))
    assert initial_state.current_stage == original_stage
    assert len(initial_state.outputs) == original_outputs_count


@pytest.mark.unit
def test_planner_agent_run_writes_artifact(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    stub_llm_client,
) -> None:
    """PlannerAgent.run() writes a lesson plan artifact to the store."""
    from forged.pipeline.agents.planner import PlannerAgent

    agent = PlannerAgent(personas_dir=personas_dir, llm_client=stub_llm_client)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(initial_state, artifact_store)
    )
    artifact_name = result.outputs[-1].artifact_name
    assert artifact_store.has(artifact_name)


@pytest.mark.unit
def test_planner_replan_message_carries_brief_and_prior_feedback(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """On replan, the planner prompt carries BOTH the original brief and the prior
    feedback — so the persona's keep-every-capability rule has the brief to anchor to
    and the replan can scaffold the weak step instead of descoping (R1, doc 11).
    """
    from forged.pipeline.agents.planner import PlannerAgent

    artifact_store.put(
        Artifact(name="brief", kind="text", content="setup and train a local LLM")
    )
    artifact_store.put(
        Artifact(
            name="revision_brief_v0",
            kind="text",
            content="MPS device selection for the Trainer isn't explained",
        )
    )
    # iteration 1 ⇒ planner reads revision_brief_v0 (state.iteration - 1).
    state = PipelineState(
        run_id="replan-run", current_stage=PipelineStage.PLANNER, iteration=1
    )

    agent = PlannerAgent(personas_dir=personas_dir, llm_client=None)
    message = agent._build_user_message(state, artifact_store)

    assert "setup and train a local LLM" in message
    assert "MPS device selection" in message
    assert "Feedback from previous attempt" in message


# ── CodeAuthorAgent tests ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_code_author_loads_persona(personas_dir: Path) -> None:
    """CodeAuthorAgent._load_persona() returns the code_author.md content."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    agent = CodeAuthorAgent(personas_dir=personas_dir)
    assert isinstance(agent.persona, str)
    assert "Code Author" in agent.persona


@pytest.mark.unit
def test_code_author_next_stage(personas_dir: Path) -> None:
    """CodeAuthorAgent.next_stage() returns PipelineStage.EXECUTOR."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    agent = CodeAuthorAgent(personas_dir=personas_dir)
    assert agent.next_stage() == PipelineStage.EXECUTOR


@pytest.mark.unit
def test_code_author_run_updates_stage(
    personas_dir: Path,
    state_with_plan: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """CodeAuthorAgent.run() returns a state with current_stage=EXECUTOR."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    agent = CodeAuthorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_plan, artifact_store)
    )
    assert result.current_stage == PipelineStage.EXECUTOR


@pytest.mark.unit
def test_code_author_run_adds_output(
    personas_dir: Path,
    state_with_plan: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """CodeAuthorAgent.run() adds one output entry with a notebook artifact name."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    agent = CodeAuthorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_plan, artifact_store)
    )
    assert len(result.outputs) == len(state_with_plan.outputs) + 1
    artifact_name = result.outputs[-1].artifact_name
    assert "notebook" in artifact_name.lower()


@pytest.mark.unit
def test_code_author_run_is_immutable(
    personas_dir: Path,
    state_with_plan: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """CodeAuthorAgent.run() never mutates the input state."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    original_stage = state_with_plan.current_stage
    original_outputs_count = len(state_with_plan.outputs)
    agent = CodeAuthorAgent(personas_dir=personas_dir)
    asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_plan, artifact_store)
    )
    assert state_with_plan.current_stage == original_stage
    assert len(state_with_plan.outputs) == original_outputs_count


# ── ExecutorAgent tests ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_executor_agent_loads_persona(personas_dir: Path) -> None:
    """ExecutorAgent._load_persona() returns a string (persona or empty string)."""
    from forged.pipeline.agents.executor import ExecutorAgent

    agent = ExecutorAgent(personas_dir=personas_dir)
    assert isinstance(agent.persona, str)


@pytest.mark.unit
def test_executor_agent_next_stage(personas_dir: Path) -> None:
    """ExecutorAgent.next_stage() returns PipelineStage.STUDENT."""
    from forged.pipeline.agents.executor import ExecutorAgent

    agent = ExecutorAgent(personas_dir=personas_dir)
    assert agent.next_stage() == PipelineStage.STUDENT


@pytest.mark.unit
def test_executor_agent_run_updates_stage(
    personas_dir: Path,
    state_with_notebook: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """ExecutorAgent.run() returns a state with current_stage=STUDENT."""
    from forged.pipeline.agents.executor import ExecutorAgent

    agent = ExecutorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_notebook, artifact_store)
    )
    assert result.current_stage == PipelineStage.STUDENT


@pytest.mark.unit
def test_executor_agent_run_returns_execution_report(
    personas_dir: Path,
    state_with_notebook: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """ExecutorAgent.run() writes an execution_report artifact to the store."""
    from forged.pipeline.agents.executor import ExecutorAgent

    agent = ExecutorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_notebook, artifact_store)
    )
    artifact_name = result.outputs[-1].artifact_name
    assert "execution" in artifact_name.lower()
    assert artifact_store.has(artifact_name)
    content = artifact_store.get(artifact_name).content
    parsed = json.loads(content)
    assert "ok" in parsed


@pytest.mark.unit
def test_executor_agent_run_is_immutable(
    personas_dir: Path,
    state_with_notebook: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """ExecutorAgent.run() never mutates the input state."""
    from forged.pipeline.agents.executor import ExecutorAgent

    original_stage = state_with_notebook.current_stage
    original_outputs_count = len(state_with_notebook.outputs)
    agent = ExecutorAgent(personas_dir=personas_dir)
    asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_notebook, artifact_store)
    )
    assert state_with_notebook.current_stage == original_stage
    assert len(state_with_notebook.outputs) == original_outputs_count


@pytest.mark.integration
def test_executor_agent_detects_failing_notebook(
    personas_dir: Path,
    state_with_failing_notebook: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """ExecutorAgent.run() detects notebook execution failures via real executor."""
    from forged.pipeline.agents.executor import ExecutorAgent

    agent = ExecutorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_failing_notebook, artifact_store)
    )

    artifact_name = result.outputs[-1].artifact_name
    assert artifact_store.has(artifact_name)
    content = artifact_store.get(artifact_name).content
    parsed = json.loads(content)

    assert parsed["ok"] is False, "Notebook with NameError should report ok=False"
    assert len(parsed["failed_cells"]) > 0, "Should detect at least one failed cell"
    assert parsed["error_summary"] is not None, "Should include error summary"
    assert "NameError" in parsed["error_summary"] or "Error" in parsed[
        "error_summary"
    ], "Error summary should mention the error type"


# ── StudentAgent tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_student_agent_loads_persona(personas_dir: Path) -> None:
    """StudentAgent._load_persona() returns the student.md content."""
    from forged.pipeline.agents.student import StudentAgent

    agent = StudentAgent(personas_dir=personas_dir)
    assert isinstance(agent.persona, str)
    assert "Student" in agent.persona


@pytest.mark.unit
def test_student_agent_next_stage(personas_dir: Path) -> None:
    """StudentAgent.next_stage() returns None — Reviser determines routing."""
    from forged.pipeline.agents.student import StudentAgent

    agent = StudentAgent(personas_dir=personas_dir)
    assert agent.next_stage() is None


@pytest.mark.unit
def test_student_agent_run_updates_stage(
    personas_dir: Path,
    state_with_execution: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """StudentAgent.run() returns a state with current_stage=REVISER."""
    from forged.pipeline.agents.student import StudentAgent

    agent = StudentAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_execution, artifact_store)
    )
    assert result.current_stage == PipelineStage.REVISER


@pytest.mark.unit
def test_student_agent_run_adds_output(
    personas_dir: Path,
    state_with_execution: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """StudentAgent.run() adds one output entry with a grade report artifact."""
    from forged.pipeline.agents.student import StudentAgent

    agent = StudentAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_execution, artifact_store)
    )
    assert len(result.outputs) == len(state_with_execution.outputs) + 1
    artifact_name = result.outputs[-1].artifact_name
    assert "grade" in artifact_name.lower() or "student" in artifact_name.lower()


@pytest.mark.unit
def test_student_agent_run_grade_report_has_quality_score(
    personas_dir: Path,
    state_with_execution: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """StudentAgent.run() writes a JSON grade report with a quality_score field."""
    from forged.pipeline.agents.student import StudentAgent

    agent = StudentAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_execution, artifact_store)
    )
    artifact_name = result.outputs[-1].artifact_name
    content = artifact_store.get(artifact_name).content
    parsed = json.loads(content)
    assert "quality_score" in parsed
    assert isinstance(parsed["quality_score"], (int, float))


@pytest.mark.unit
def test_student_agent_run_is_immutable(
    personas_dir: Path,
    state_with_execution: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """StudentAgent.run() never mutates the input state."""
    from forged.pipeline.agents.student import StudentAgent

    original_stage = state_with_execution.current_stage
    original_outputs_count = len(state_with_execution.outputs)
    agent = StudentAgent(personas_dir=personas_dir)
    asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_execution, artifact_store)
    )
    assert state_with_execution.current_stage == original_stage
    assert len(state_with_execution.outputs) == original_outputs_count


# ── RevisorAgent tests ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_revisor_agent_loads_persona(personas_dir: Path) -> None:
    """RevisorAgent._load_persona() returns a non-empty string."""
    from forged.pipeline.agents.reviser import RevisorAgent

    agent = RevisorAgent(personas_dir=personas_dir)
    assert isinstance(agent.persona, str)


@pytest.mark.unit
def test_revisor_agent_next_stage(personas_dir: Path) -> None:
    """RevisorAgent.next_stage() returns None — routing is done by the graph."""
    from forged.pipeline.agents.reviser import RevisorAgent

    agent = RevisorAgent(personas_dir=personas_dir)
    assert agent.next_stage() is None


@pytest.mark.unit
def test_revisor_agent_run_adds_routing_decision(
    personas_dir: Path,
    state_with_grade: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """RevisorAgent.run() returns state with at least one routing_log entry."""
    from forged.pipeline.agents.reviser import RevisorAgent

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_grade, artifact_store)
    )
    # Either routing_log grew (non-terminal) or is_terminal was set
    routing_grew = len(result.routing_log) > len(state_with_grade.routing_log)
    became_terminal = result.is_terminal
    assert routing_grew or became_terminal


@pytest.mark.unit
def test_revisor_terminates_on_hollow_executed_notebook(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """A green, well-graded run whose executed notebook is hollow must NOT be accepted.

    End-to-end through the reviser: the structural gate reads the executed notebook
    from the run dir and forces a non-acceptable terminal state.
    """
    import nbformat

    from forged.executor import executed_notebook_filename
    from forged.pipeline.agents.reviser import RevisorAgent

    # Hollow executed notebook: most code cells printed a skip message.
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_markdown_cell("# Lesson")]
    for text in (
        "Missing prerequisites detected",
        "Baseline generation skipped: missing torch",
        "Training skipped: missing deps",
        "Post-training generation skipped",
    ):
        cell = nbformat.v4.new_code_cell("...")
        cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text=text)]
        nb.cells.append(cell)
    (artifact_store.run_dir / executed_notebook_filename("execution_report_v0")).write_text(
        nbformat.writes(nb), encoding="utf-8"
    )

    # State: executor ran (ok) and student graded high — would normally be ACCEPTABLE.
    state = create_initial_state(run_id="hollow-run")
    artifact_store.put(
        Artifact(
            name="execution_report_v0",
            kind="json",
            content=json.dumps({"ok": True, "failed_cells": [], "error_summary": None}),
        )
    )
    grade = {"quality_score": 90.0, "graded": True, "blockers": [], "findings": []}
    artifact_store.put(
        Artifact(name="student_grade_report_v0", kind="json", content=json.dumps(grade))
    )
    state = (
        state.with_output(
            StageOutput(
                stage=PipelineStage.EXECUTOR,
                artifact_name="execution_report_v0",
                iteration=0,
            )
        )
        .with_output(
            StageOutput(
                stage=PipelineStage.STUDENT,
                artifact_name="student_grade_report_v0",
                iteration=0,
            )
        )
        .with_current_stage(PipelineStage.REVISER)
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert result.is_terminal is True
    assert result.terminal_ok is False
    assert "skipped" in (result.terminal_reason or "")


@pytest.mark.unit
def test_revisor_records_topic_fidelity_signal_when_capability_dropped(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """A clean run that dropped a requested capability records a fidelity signal.

    The notebook sets up a model but never trains it; topic_spec.json asked for both.
    The reviser must record a TopicFidelitySignal with the training capability in
    `missing` so the drop is visible even when the run is otherwise ACCEPTABLE (R1).
    """
    import nbformat

    from forged.executor import executed_notebook_filename
    from forged.pipeline.agents.reviser import RevisorAgent

    # Executed notebook: setup only, training removed.
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_markdown_cell("# Set up and run a local LLM"),
        nbformat.v4.new_code_cell("model = load_local_llm()\nprint(model.generate('hi'))"),
    ]
    (artifact_store.run_dir / executed_notebook_filename("execution_report_v0")).write_text(
        nbformat.writes(nb), encoding="utf-8"
    )

    artifact_store.put(
        Artifact(
            name="topic_spec",
            kind="json",
            content=json.dumps(
                {
                    "title": "Setup and train a local LLM",
                    "learning_objectives": [
                        "Set up a local LLM",
                        "Fine-tune the model with LoRA",
                    ],
                    "focus_areas": [],
                }
            ),
        )
    )
    artifact_store.put(
        Artifact(
            name="execution_report_v0",
            kind="json",
            content=json.dumps({"ok": True, "failed_cells": [], "error_summary": None}),
        )
    )
    artifact_store.put(
        Artifact(
            name="student_grade_report_v0",
            kind="json",
            content=json.dumps(
                {"quality_score": 90.0, "graded": True, "blockers": [], "findings": []}
            ),
        )
    )
    state = (
        create_initial_state(run_id="fidelity-run")
        .with_output(
            StageOutput(
                stage=PipelineStage.EXECUTOR, artifact_name="execution_report_v0", iteration=0
            )
        )
        .with_output(
            StageOutput(
                stage=PipelineStage.STUDENT,
                artifact_name="student_grade_report_v0",
                iteration=0,
            )
        )
        .with_current_stage(PipelineStage.REVISER)
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert len(result.topic_fidelity) == 1
    signal = result.topic_fidelity[0]
    assert "Fine-tune the model with LoRA" in signal.missing
    assert "Set up a local LLM" in signal.covered
    assert signal.source == "deterministic"


@pytest.mark.unit
def test_revision_brief_includes_rubric_and_cell_reference(personas_dir: Path) -> None:
    """The brief carries the rubric breakdown and cell-referenced findings.

    A rerouted agent should get specifics (which dimension is weak, which cell to
    look at), not just a generic 'revise the lesson' instruction.
    """
    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.failure import (
        Classification,
        ExecutionReport,
        FailureCategory,
        GradeReport,
        RubricScores,
    )
    from forged.pipeline.state import Evidence, Location, LocationType, PipelineStage

    rubric = RubricScores(
        structure=70, explanation_depth=30, code_clarity=80, correctness=85, learner_fit=40
    )
    finding = Evidence(
        source="student",
        severity="CONFUSING",
        scope="content",
        location=Location(type=LocationType.CELL, cell_index=4),
        text="Label masking is used but never explained",
    )
    grade = GradeReport(quality_score=61.0, rubric=rubric, findings=[finding])
    classification = Classification(
        category=FailureCategory.CONTENT_QUALITY, reason="Quality below threshold"
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    brief = agent._synthesize_revision_brief(
        ExecutionReport(ok=True), grade, classification, PipelineStage.CODE_AUTHOR
    )

    assert "explanation_depth 30" in brief
    assert "cell 4 —" in brief
    assert "Label masking" in brief


@pytest.mark.unit
def test_revisor_agent_run_reads_classification(
    personas_dir: Path,
    state_with_grade: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """RevisorAgent.run() calls classify() and uses the result to route."""
    from forged.pipeline.agents.reviser import RevisorAgent

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_grade, artifact_store)
    )
    # With quality_score=90 (above threshold=80) and ok=True, should terminate as ACCEPTABLE
    assert result.is_terminal


def _put_reviewer_report(store: ArtifactStore, findings: list[dict], blockers=None) -> None:
    store.put(
        Artifact(
            name="reviewer_report_v0",
            kind="json",
            content=json.dumps(
                {"reviewed": True, "blockers": blockers or [], "findings": findings}
            ),
        )
    )


@pytest.mark.unit
def test_reviewer_code_blocker_routes_to_code_author(
    personas_dir: Path,
    state_with_grade: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """A reviewer correctness BLOCKER routes back to the code author even when the
    student's grade is clean — the whole point of the second critic."""
    from forged.pipeline.agents.reviser import RevisorAgent

    _put_reviewer_report(
        artifact_store,
        findings=[
            {
                "source": "reviewer",
                "severity": "BLOCKER",
                "scope": "code",
                "location": {"type": "cell", "cell_index": 3},
                "text": "torch.foo() is not a real API; this cell cannot be correct.",
            }
        ],
    )
    state = state_with_grade.with_output(
        StageOutput(
            stage=PipelineStage.REVIEWER,
            artifact_name="reviewer_report_v0",
            iteration=0,
        )
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert not result.is_terminal, "A reviewer code blocker must reroute, not terminate"
    assert result.current_stage == PipelineStage.CODE_AUTHOR
    assert result.routing_log[-1].classification == "test_failure"


@pytest.mark.unit
def test_reviewer_cell_finding_without_index_does_not_crash(
    personas_dir: Path,
    state_with_grade: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """A reviewer finding tagged location.type='cell' but missing cell_index must not
    crash the routing loop. Real LLM output routinely omits the index; the reviser
    downgrades the location to GLOBAL and keeps the finding (routes by scope), rather
    than raising the state.Location CELL-requires-cell_index invariant mid-pipeline."""
    from forged.pipeline.agents.reviser import RevisorAgent

    _put_reviewer_report(
        artifact_store,
        findings=[
            {
                "source": "reviewer",
                "severity": "BLOCKER",
                "scope": "code",
                "location": {"type": "cell"},  # cell type, no cell_index
                "text": "This cell calls a nonexistent API.",
            }
        ],
    )
    state = state_with_grade.with_output(
        StageOutput(
            stage=PipelineStage.REVIEWER,
            artifact_name="reviewer_report_v0",
            iteration=0,
        )
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    # The finding survived the downgrade: a code BLOCKER still reroutes to the author.
    assert not result.is_terminal
    assert result.current_stage == PipelineStage.CODE_AUTHOR
    assert result.routing_log[-1].classification == "test_failure"


@pytest.mark.unit
def test_clean_reviewer_leaves_acceptable_grade_untouched(
    personas_dir: Path,
    state_with_grade: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """An empty reviewer report must not perturb an otherwise-acceptable run."""
    from forged.pipeline.agents.reviser import RevisorAgent

    _put_reviewer_report(artifact_store, findings=[])
    state = state_with_grade.with_output(
        StageOutput(
            stage=PipelineStage.REVIEWER,
            artifact_name="reviewer_report_v0",
            iteration=0,
        )
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert result.is_terminal
    assert result.terminal_ok is True


@pytest.mark.unit
def test_reviewer_agent_writes_parseable_report(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """ReviewerAgent parses the LLM's trailing JSON block into a findings report."""
    from forged.pipeline.agents.reviewer import ReviewerAgent

    class StubLLMClient:
        def complete(
            self,
            system_prompt: str,
            user_prompt: str,
            trace_context=None,
            response_format=None,
        ) -> str:
            return (
                "Prose verdict: one correctness issue.\n\n"
                "```json\n"
                '{"blockers": ["cell 3 uses a non-existent API"], '
                '"findings": [{"source": "reviewer", "severity": "BLOCKER", '
                '"scope": "code", "location": {"type": "cell", "cell_index": 3}, '
                '"text": "Non-existent API call"}]}\n'
                "```"
            )

    artifact_store.put(
        Artifact(name="lesson_notebook_v0", kind="notebook", content="# notebook text")
    )
    artifact_store.put(
        Artifact(name="execution_report_v0", kind="json", content='{"ok": true}')
    )
    state = create_initial_state(run_id="reviewer-parse")

    agent = ReviewerAgent(personas_dir=personas_dir, llm_client=StubLLMClient())
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    report = json.loads(artifact_store.get("reviewer_report_v0").content)
    assert report["reviewed"] is True
    assert report["findings"][0]["scope"] == "code"
    assert result.current_stage == PipelineStage.REVISER


@pytest.mark.unit
def test_reviewer_agent_requests_structured_findings_schema(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """ReviewerAgent asks capable providers for a strict JSON-schema findings report."""
    from forged.pipeline.agents.reviewer import ReviewerAgent

    class StubLLMClient:
        def __init__(self) -> None:
            self.response_format = None

        def complete(
            self,
            system_prompt: str,
            user_prompt: str,
            trace_context=None,
            response_format=None,
        ) -> str:
            self.response_format = response_format
            return '{"blockers": [], "findings": []}'

    artifact_store.put(
        Artifact(name="lesson_notebook_v0", kind="notebook", content="# notebook text")
    )
    artifact_store.put(
        Artifact(name="execution_report_v0", kind="json", content='{"ok": true}')
    )
    state = create_initial_state(run_id="reviewer-schema")
    llm_client = StubLLMClient()

    agent = ReviewerAgent(personas_dir=personas_dir, llm_client=llm_client)
    asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert llm_client.response_format["type"] == "json_schema"
    assert llm_client.response_format["json_schema"]["name"] == "reviewer_findings_report"
    assert llm_client.response_format["json_schema"]["strict"] is True
    assert {"blockers", "findings"} <= set(
        llm_client.response_format["json_schema"]["schema"]["required"]
    )


@pytest.mark.unit
def test_revisor_agent_run_respects_budget(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """RevisorAgent.run() respects Router budget and terminates when exhausted."""
    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.router import RoutingBudget

    # State at REVISER with grade report showing low quality (triggers CONTENT_QUALITY)
    state = create_initial_state(run_id="test-budget-001")
    state = state.with_current_stage(PipelineStage.REVISER)
    # Exhaust the content-reviser budget (CONTENT_QUALITY's target) by setting its
    # attempts to 1 (matches default budget=1).
    state = state.with_attempt(PipelineStage.CONTENT_REVISER)

    exec_report = {"ok": True, "failed_cells": [], "error_summary": None}
    grade_report = {
        "quality_score": 40.0,  # Below 80 → CONTENT_QUALITY → routes to CONTENT_REVISER
        "blockers": [],
        "findings": [],
    }
    artifact_store.put(
        Artifact(
            name="execution_report_v0",
            kind="json",
            content=json.dumps(exec_report),
        )
    )
    artifact_store.put(
        Artifact(
            name="student_grade_report_v0",
            kind="json",
            content=json.dumps(grade_report),
        )
    )
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name="student_grade_report_v0",
            iteration=0,
        )
    )

    agent = RevisorAgent(personas_dir=personas_dir, budget=RoutingBudget(content_reviser=1))
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state, artifact_store)
    )
    # Budget for content_reviser is 1, already used 1 — should terminate
    assert result.is_terminal


@pytest.mark.unit
def test_revisor_agent_run_is_immutable(
    personas_dir: Path,
    state_with_grade: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """RevisorAgent.run() never mutates the input state."""
    from forged.pipeline.agents.reviser import RevisorAgent

    original_stage = state_with_grade.current_stage
    original_routing_log_len = len(state_with_grade.routing_log)
    agent = RevisorAgent(personas_dir=personas_dir)
    asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_grade, artifact_store)
    )
    assert state_with_grade.current_stage == original_stage
    assert len(state_with_grade.routing_log) == original_routing_log_len


# ── Shared cross-agent tests ──────────────────────────────────────────────────


@pytest.mark.unit
def test_all_agents_are_async(personas_dir: Path) -> None:
    """Every concrete agent's run() must be an async coroutine function."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.agents.student import StudentAgent

    agent_classes = [
        PlannerAgent,
        CodeAuthorAgent,
        ExecutorAgent,
        StudentAgent,
        RevisorAgent,
    ]
    for cls in agent_classes:
        assert inspect.iscoroutinefunction(cls.run), (
            f"{cls.__name__}.run() must be an async coroutine function"
        )


@pytest.mark.unit
def test_all_agents_implement_abstract_methods(personas_dir: Path) -> None:
    """Every concrete agent can be instantiated without TypeError (all abstracts implemented)."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.agents.planner import PlannerAgent
    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.agents.student import StudentAgent

    for cls in [PlannerAgent, CodeAuthorAgent, ExecutorAgent, StudentAgent, RevisorAgent]:
        instance = cls(personas_dir=personas_dir)
        assert instance is not None, f"{cls.__name__} could not be instantiated"


@pytest.mark.unit
def test_planner_output_stage_matches(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    stub_llm_client,
) -> None:
    """PlannerAgent output StageOutput.stage == PipelineStage.PLANNER."""
    from forged.pipeline.agents.planner import PlannerAgent

    agent = PlannerAgent(personas_dir=personas_dir, llm_client=stub_llm_client)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(initial_state, artifact_store)
    )
    assert result.outputs[-1].stage == PipelineStage.PLANNER


@pytest.mark.unit
def test_code_author_output_stage_matches(
    personas_dir: Path,
    state_with_plan: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """CodeAuthorAgent output StageOutput.stage == PipelineStage.CODE_AUTHOR."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    agent = CodeAuthorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_plan, artifact_store)
    )
    assert result.outputs[-1].stage == PipelineStage.CODE_AUTHOR


@pytest.mark.unit
def test_executor_output_stage_matches(
    personas_dir: Path,
    state_with_notebook: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """ExecutorAgent output StageOutput.stage == PipelineStage.EXECUTOR."""
    from forged.pipeline.agents.executor import ExecutorAgent

    agent = ExecutorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_notebook, artifact_store)
    )
    assert result.outputs[-1].stage == PipelineStage.EXECUTOR


@pytest.mark.unit
def test_student_output_stage_matches(
    personas_dir: Path,
    state_with_execution: PipelineState,
    artifact_store: ArtifactStore,
) -> None:
    """StudentAgent output StageOutput.stage == PipelineStage.STUDENT."""
    from forged.pipeline.agents.student import StudentAgent

    agent = StudentAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state_with_execution, artifact_store)
    )
    assert result.outputs[-1].stage == PipelineStage.STUDENT


@pytest.mark.unit
def test_revisor_low_quality_routes_to_content_reviser_when_budget_allows(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """RevisorAgent with a CONTENT_QUALITY signal routes to CONTENT_REVISER when budget allows."""
    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.router import RoutingBudget

    state = create_initial_state(run_id="test-routing-001")
    state = state.with_current_stage(PipelineStage.REVISER)

    exec_report = {"ok": True, "failed_cells": [], "error_summary": None}
    grade_report = {
        "quality_score": 40.0,
        "blockers": [],
        "findings": [],
    }
    artifact_store.put(
        Artifact(name="execution_report_v0", kind="json", content=json.dumps(exec_report))
    )
    artifact_store.put(
        Artifact(name="student_grade_report_v0", kind="json", content=json.dumps(grade_report))
    )
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.STUDENT, artifact_name="student_grade_report_v0", iteration=0
        )
    )

    # Budget with content_reviser=2 so the first route still has budget
    agent = RevisorAgent(personas_dir=personas_dir, budget=RoutingBudget(content_reviser=2))
    result = asyncio.get_event_loop().run_until_complete(
        agent.run(state, artifact_store)
    )
    # Should NOT terminate — should route (routing_log grows)
    assert not result.is_terminal
    assert len(result.routing_log) > 0
    assert result.get_stage_attempt_count(PipelineStage.CONTENT_REVISER) == 1


@pytest.mark.unit
def test_revisor_accepts_notebook_level_findings_from_real_llm_output(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """Notebook-level findings from the live student prompt should not crash parsing."""
    from forged.pipeline.agents.reviser import RevisorAgent

    state = create_initial_state(run_id="test-routing-notebook-001")
    state = state.with_current_stage(PipelineStage.REVISER)

    exec_report = {"ok": True, "failed_cells": [], "error_summary": None}
    grade_report = {
        "quality_score": 70.0,
        "blockers": [],
        "findings": [
            {
                "source": "student",
                "severity": "NITPICK",
                "scope": "notebook",
                "location": {"type": "notebook", "cell_index": None, "label": None},
                "text": "Needs a stronger end-to-end example.",
            }
        ],
    }
    artifact_store.put(
        Artifact(name="execution_report_v0", kind="json", content=json.dumps(exec_report))
    )
    artifact_store.put(
        Artifact(name="student_grade_report_v0", kind="json", content=json.dumps(grade_report))
    )
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.STUDENT, artifact_name="student_grade_report_v0", iteration=0
        )
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert result.is_terminal or len(result.routing_log) > len(state.routing_log)


@pytest.mark.unit
def test_revisor_handles_malformed_grade_report_json_gracefully(
    personas_dir: Path,
    artifact_store: ArtifactStore,
) -> None:
    """Malformed grade-report JSON should degrade to termination, not crash the pipeline."""
    from forged.pipeline.agents.reviser import RevisorAgent

    state = create_initial_state(run_id="test-routing-bad-json-001")
    state = state.with_current_stage(PipelineStage.REVISER)
    artifact_store.put(
        Artifact(
            name="execution_report_v0",
            kind="json",
            content=json.dumps({"ok": True, "failed_cells": [], "error_summary": None}),
        )
    )
    artifact_store.put(
        Artifact(name="student_grade_report_v0", kind="json", content="{not valid json")
    )
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.STUDENT, artifact_name="student_grade_report_v0", iteration=0
        )
    )

    agent = RevisorAgent(personas_dir=personas_dir)
    result = asyncio.get_event_loop().run_until_complete(agent.run(state, artifact_store))

    assert result.is_terminal
