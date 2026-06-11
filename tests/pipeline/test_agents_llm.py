"""Tests for the LLM-wired agents (Phase 6).

All tests inject a mock LLMClient so no real API calls are made.
Covers:
  - PlannerAgent: calls LLM with correct system+user message, propagates errors
  - CodeAuthorAgent: strips ```json fences, validates JSON array, errors on bad JSON
  - StudentAgent: parses JSON grade report, degrades gracefully on bad responses

TDD: written FIRST (RED) before implementation was complete.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from forged.artifacts import ArtifactStore
from forged.pipeline.state import PipelineState, create_initial_state

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    """Temporary personas dir populated with all required persona files."""
    d = tmp_path / "personas"
    d.mkdir()
    (d / "planner.md").write_text("You are the Planner.", encoding="utf-8")
    (d / "code_author.md").write_text("You are the Code Author.", encoding="utf-8")
    (d / "student.md").write_text("You are the Student.", encoding="utf-8")
    (d / "reviser.md").write_text("You are the Reviser.", encoding="utf-8")
    return d


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


@pytest.fixture
def initial_state() -> PipelineState:
    return create_initial_state(run_id="llm-test-001")


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """A mock LLMClient whose complete() method returns a configurable string."""
    client = MagicMock()
    client.complete = MagicMock(return_value="default mock response")
    return client


# ── PlannerAgent LLM tests ────────────────────────────────────────────────────


@pytest.mark.unit
def test_planner_calls_llm_with_persona_as_system_prompt(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """PlannerAgent.run() calls LLMClient.complete() with the persona as system prompt."""
    from forged.pipeline.agents.planner import PlannerAgent

    mock_llm_client.complete.return_value = "# Plan\n\nLesson content here."
    agent = PlannerAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    mock_llm_client.complete.assert_called_once()
    call_args = mock_llm_client.complete.call_args
    # First positional arg is the system prompt (persona)
    system_prompt = call_args[0][0]
    assert "Planner" in system_prompt


@pytest.mark.unit
def test_planner_calls_llm_with_user_message_containing_run_id(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """PlannerAgent._build_user_message() includes run_id and iteration."""
    from forged.pipeline.agents.planner import PlannerAgent

    mock_llm_client.complete.return_value = "# Plan content"
    agent = PlannerAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    call_args = mock_llm_client.complete.call_args
    user_msg = call_args[0][1]
    assert "llm-test-001" in user_msg


@pytest.mark.unit
def test_planner_propagates_llm_runtime_error(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """PlannerAgent.run() raises RuntimeError when the LLM call fails."""
    from forged.pipeline.agents.planner import PlannerAgent

    mock_llm_client.complete.side_effect = RuntimeError("API timeout")
    agent = PlannerAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    with pytest.raises(RuntimeError, match="PlannerAgent LLM call failed"):
        asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))


# ── CodeAuthorAgent LLM tests ─────────────────────────────────────────────────


@pytest.mark.unit
def test_code_author_strips_json_fence_and_parses_array(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """CodeAuthorAgent._parse_cells() strips ```json fences and assembles valid nbformat."""
    import nbformat

    from forged.pipeline.agents.code_author import CodeAuthorAgent

    cells = [{"type": "code", "source": "print('hello')"}]
    fenced_response = f"```json\n{json.dumps(cells)}\n```"
    mock_llm_client.complete.return_value = fenced_response

    agent = CodeAuthorAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = artifact_store.get(artifact_name).content
    notebook = nbformat.reads(stored, as_version=4)  # executor contract: must not raise
    assert notebook.cells[0].cell_type == "code"
    assert notebook.cells[0].source == "print('hello')"


@pytest.mark.unit
def test_code_author_accepts_bare_json_array(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """CodeAuthorAgent._parse_cells() accepts a bare JSON array without fences."""
    import nbformat

    from forged.pipeline.agents.code_author import CodeAuthorAgent

    cells = [{"type": "markdown", "source": "# Intro"}]
    mock_llm_client.complete.return_value = json.dumps(cells)

    agent = CodeAuthorAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = artifact_store.get(artifact_name).content
    notebook = nbformat.reads(stored, as_version=4)
    assert notebook.cells[0].cell_type == "markdown"


@pytest.mark.unit
def test_code_author_falls_back_on_invalid_json(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """CodeAuthorAgent.run() falls back to fallback cells when LLM returns invalid JSON."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    mock_llm_client.complete.return_value = "Here are some cells: {broken json"
    agent = CodeAuthorAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    # Should not raise — should fall back
    import nbformat

    artifact_name = result.outputs[-1].artifact_name
    assert artifact_store.has(artifact_name)
    stored = artifact_store.get(artifact_name).content
    # Fallback must also satisfy the executor contract: valid nbformat
    notebook = nbformat.reads(stored, as_version=4)
    assert len(notebook.cells) > 0


@pytest.mark.unit
def test_code_author_calls_llm_with_persona_as_system_prompt(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """CodeAuthorAgent.run() passes the persona as the system prompt to the LLM."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent

    mock_llm_client.complete.return_value = json.dumps([{"type": "code", "source": "x=1"}])
    agent = CodeAuthorAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    mock_llm_client.complete.assert_called_once()
    system_prompt = mock_llm_client.complete.call_args[0][0]
    assert "Code Author" in system_prompt


# ── StudentAgent LLM tests ────────────────────────────────────────────────────


@pytest.mark.unit
def test_student_parses_json_grade_report_from_fence(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """StudentAgent._parse_grade_report() extracts JSON from a trailing ```json fence."""
    from forged.pipeline.agents.student import StudentAgent

    report = {"quality_score": 78.5, "blockers": [], "findings": []}
    llm_response = f"Narrative findings here.\n\n```json\n{json.dumps(report)}\n```"
    mock_llm_client.complete.return_value = llm_response

    agent = StudentAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = json.loads(artifact_store.get(artifact_name).content)
    assert stored["quality_score"] == pytest.approx(78.5)
    assert stored["blockers"] == []
    assert stored["findings"] == []


@pytest.mark.unit
def test_student_parses_bare_json_object(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """StudentAgent._parse_grade_report() parses a bare JSON object in the response."""
    from forged.pipeline.agents.student import StudentAgent

    report = {"quality_score": 65.0, "blockers": ["missing setup cell"], "findings": []}
    mock_llm_client.complete.return_value = (
        "Some prose\n" + json.dumps(report)
    )

    agent = StudentAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = json.loads(artifact_store.get(artifact_name).content)
    assert "quality_score" in stored


@pytest.mark.unit
def test_student_degrades_gracefully_on_unparseable_response(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """StudentAgent.run() uses neutral report when LLM response contains no valid JSON."""
    from forged.pipeline.agents.student import StudentAgent

    mock_llm_client.complete.return_value = "I reviewed the notebook. Looks fine overall."
    agent = StudentAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = json.loads(artifact_store.get(artifact_name).content)
    # Neutral fallback values
    assert stored["quality_score"] == pytest.approx(50.0)
    assert stored["blockers"] == []
    assert stored["findings"] == []


@pytest.mark.unit
def test_student_degrades_gracefully_on_llm_error(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """StudentAgent.run() uses neutral report when the LLM call itself raises RuntimeError."""
    from forged.pipeline.agents.student import StudentAgent

    mock_llm_client.complete.side_effect = RuntimeError("quota exceeded")
    agent = StudentAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = json.loads(artifact_store.get(artifact_name).content)
    assert stored["quality_score"] == pytest.approx(50.0)


@pytest.mark.unit
def test_student_calls_llm_with_persona_as_system_prompt(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """StudentAgent.run() passes the student persona as the system prompt."""
    from forged.pipeline.agents.student import StudentAgent

    report = {"quality_score": 80.0, "blockers": [], "findings": []}
    mock_llm_client.complete.return_value = json.dumps(report)
    agent = StudentAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    system_prompt = mock_llm_client.complete.call_args[0][0]
    assert "Student" in system_prompt


@pytest.mark.unit
def test_student_grade_report_missing_keys_degrades(
    personas_dir: Path,
    initial_state: PipelineState,
    artifact_store: ArtifactStore,
    mock_llm_client: MagicMock,
) -> None:
    """StudentAgent._parse_grade_report() degrades when required keys are missing."""
    from forged.pipeline.agents.student import StudentAgent

    # JSON object but missing 'findings' key
    mock_llm_client.complete.return_value = '{"quality_score": 70.0, "blockers": []}'
    agent = StudentAgent(personas_dir=personas_dir, llm_client=mock_llm_client)
    result = asyncio.get_event_loop().run_until_complete(agent.run(initial_state, artifact_store))

    artifact_name = result.outputs[-1].artifact_name
    stored = json.loads(artifact_store.get(artifact_name).content)
    # Should fall back to neutral
    assert stored["quality_score"] == pytest.approx(50.0)
