"""Un-mocked integration: real CodeAuthorAgent output through the real executor.

These tests stub only the LLM transport (no network) and otherwise exercise the
real agent code paths. They exist because the format contract between
CodeAuthorAgent (writes the notebook artifact) and ExecutorStage
(`nbformat.reads()` on that artifact) was previously verified only with
hand-built nbformat fixtures — which masked a production crash where the
CodeAuthor stored a bare JSON cell array that the executor could not read.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import nbformat
import pytest

from forged.artifacts import ArtifactStore
from forged.pipeline.state import PipelineStage, PipelineState

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    """Temporary personas directory populated with all required persona files."""
    d = tmp_path / "personas"
    d.mkdir()
    for name in ("planner", "code_author", "student", "reviser"):
        (d / f"{name}.md").write_text(f"Persona for {name}.", encoding="utf-8")
    return d


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    """ArtifactStore writing to a temp run directory."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


class StubLLMClient:
    """Stands in for LLMClient: returns a canned response, no network."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self._response


_WORKING_CELLS = json.dumps(
    [
        {"type": "markdown", "source": "# Lesson\n\nA tiny lesson."},
        {"type": "code", "source": "x = 2 + 2\nprint(x)"},
    ]
)

_FAILING_CELLS = json.dumps(
    [
        {"type": "markdown", "source": "# Lesson\n\nA broken lesson."},
        {"type": "code", "source": "undefined_variable_that_will_fail"},
    ]
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _author_then_execute(
    personas_dir: Path, store: ArtifactStore, llm_response: str
) -> tuple[PipelineState, dict]:
    """Run the real CodeAuthorAgent then the real ExecutorAgent; return final state + report."""
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.agents.executor import ExecutorAgent
    from forged.pipeline.state import create_initial_state

    state = create_initial_state(run_id="real-integration")
    author = CodeAuthorAgent(
        personas_dir=personas_dir, llm_client=StubLLMClient(llm_response)
    )
    state = _run(author.run(state, store))

    executor = ExecutorAgent(personas_dir=personas_dir)
    state = _run(executor.run(state, store))

    report_name = state.outputs[-1].artifact_name
    report = json.loads(store.get(report_name).content)
    return state, report


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_code_author_artifact_is_valid_nbformat(
    personas_dir: Path, artifact_store: ArtifactStore
) -> None:
    """The notebook artifact the CodeAuthor stores must be readable by nbformat.

    This is the contract the real executor depends on (executor.py calls
    nbformat.reads on the artifact content).
    """
    from forged.pipeline.agents.code_author import CodeAuthorAgent
    from forged.pipeline.state import create_initial_state

    agent = CodeAuthorAgent(
        personas_dir=personas_dir, llm_client=StubLLMClient(_WORKING_CELLS)
    )
    state = _run(agent.run(create_initial_state(run_id="t"), artifact_store))

    content = artifact_store.get(state.outputs[-1].artifact_name).content
    notebook = nbformat.reads(content, as_version=4)  # must not raise
    assert len(notebook.cells) == 2
    assert notebook.cells[1].cell_type == "code"


@pytest.mark.integration
def test_real_code_author_output_executes_in_real_executor(
    personas_dir: Path, artifact_store: ArtifactStore
) -> None:
    """Real CodeAuthor output runs through the real executor without crashing."""
    state, report = _author_then_execute(personas_dir, artifact_store, _WORKING_CELLS)

    assert not state.is_terminal, (
        f"Executor must not crash on real CodeAuthor output "
        f"(terminal_reason={state.terminal_reason!r})"
    )
    assert state.current_stage == PipelineStage.STUDENT
    assert report["ok"] is True
    assert report["failed_cells"] == []


@pytest.mark.integration
def test_real_executor_detects_failure_in_real_code_author_output(
    personas_dir: Path, artifact_store: ArtifactStore
) -> None:
    """A failing cell written by the real CodeAuthor is detected, not crashed on."""
    state, report = _author_then_execute(personas_dir, artifact_store, _FAILING_CELLS)

    assert not state.is_terminal
    assert report["ok"] is False
    assert len(report["failed_cells"]) > 0
    assert "NameError" in (report["error_summary"] or "")


@pytest.mark.integration
def test_fallback_cells_are_also_valid_nbformat(
    personas_dir: Path, artifact_store: ArtifactStore
) -> None:
    """When the LLM response is unparseable, the fallback notebook must still execute."""
    state, report = _author_then_execute(
        personas_dir, artifact_store, "this is not json at all"
    )

    assert not state.is_terminal
    assert report["ok"] is True
