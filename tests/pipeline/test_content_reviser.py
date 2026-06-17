"""Unit tests for the ContentReviserAgent (Phase 4).

The agentic pipeline used to route CONTENT_QUALITY to a no-op deterministic node
that never rewrote anything (P1: a dead route). ContentReviserAgent is the real
LLM agent that now consumes the graded notebook + the reviser's findings and emits
a rewritten notebook for the executor to re-run and the student to re-grade.

These tests mock the LLM — no API calls. They assert it produces a new notebook
version, hands to the executor, and degrades honestly (keeping the prior notebook,
recording a Degradation) rather than collapsing to a stub when the model fails.

Run with:
    pytest tests/pipeline/test_content_reviser.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import nbformat
import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.agents.content_reviser import ContentReviserAgent
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)

# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    d = tmp_path / "personas"
    d.mkdir()
    (d / "reviser.md").write_text("Reviser persona.", encoding="utf-8")
    return d


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


def _seed_notebook(store: ArtifactStore, name: str) -> str:
    """Put a minimal valid nbformat notebook artifact and return its name."""
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_markdown_cell("# Lesson"), nbformat.v4.new_code_cell("x = 1")]
    store.put(Artifact(name=name, kind="notebook", content=nbformat.writes(nb)))
    return name


def _state_with_notebook(store: ArtifactStore) -> PipelineState:
    """A state as it would be when routed to the content reviser: code_author emitted
    a notebook at iteration 0, the reviser wrote revision_brief_v0 and bumped the
    iteration to 1, so the content reviser runs at iteration 1 and reads the v0 notebook."""
    name = _seed_notebook(store, "lesson_notebook_v0")
    store.put(Artifact(name="revision_brief_v0", kind="text", content="Explain keys."))
    state = create_initial_state(run_id="cr-001")
    state = state.with_output(
        StageOutput(stage=PipelineStage.CODE_AUTHOR, artifact_name=name, iteration=0)
    )
    return PipelineState(
        run_id=state.run_id,
        current_stage=PipelineStage.CONTENT_REVISER,
        iteration=1,
        outputs=state.outputs,
    )


# A valid reviser response: a JSON array of cells (no fence), per personas/reviser.md.
_REWRITE = json.dumps(
    [
        {"type": "markdown", "source": "# Lesson\n\nA key maps to a value."},
        {"type": "code", "source": "x = 1\nprint(x)"},
    ]
)


def _agent(personas_dir: Path, llm_response: str | Exception) -> ContentReviserAgent:
    """Build the agent with a stub LLM client returning a fixed response (or raising)."""

    class StubLLM:
        def complete(self, *args, **kwargs):
            if isinstance(llm_response, Exception):
                raise llm_response
            return llm_response

    return ContentReviserAgent(personas_dir=personas_dir, llm_client=StubLLM())


# ── Happy path ──────────────────────────────────────────────────────────────────


def test_produces_a_new_notebook_version_and_hands_to_executor(personas_dir, store):
    state = _state_with_notebook(store)
    agent = _agent(personas_dir, _REWRITE)

    result = asyncio.run(agent.run(state, store))

    assert result.current_stage == PipelineStage.EXECUTOR
    new_output = result.outputs[-1]
    assert new_output.stage == PipelineStage.CONTENT_REVISER
    # A fresh notebook artifact exists and is valid nbformat with the rewritten prose.
    assert store.has(new_output.artifact_name)
    nb = nbformat.reads(store.get(new_output.artifact_name).content, as_version=4)
    assert any("maps to a value" in c.source for c in nb.cells)
    assert not result.degradations


def test_new_notebook_is_a_distinct_artifact_from_the_input(personas_dir, store):
    state = _state_with_notebook(store)
    original = store.get("lesson_notebook_v0").content
    agent = _agent(personas_dir, _REWRITE)

    result = asyncio.run(agent.run(state, store))

    new_name = result.outputs[-1].artifact_name
    assert store.get(new_name).content != original


# ── Honest degradation ──────────────────────────────────────────────────────────


def test_llm_failure_keeps_prior_notebook_and_records_degradation(personas_dir, store):
    state = _state_with_notebook(store)
    original = store.get("lesson_notebook_v0").content
    agent = _agent(personas_dir, RuntimeError("boom"))

    result = asyncio.run(agent.run(state, store))

    # Still advances to the executor (the loop must make progress / terminate)...
    assert result.current_stage == PipelineStage.EXECUTOR
    # ...but the prior notebook is preserved (no stub collapse)...
    new_name = result.outputs[-1].artifact_name
    assert store.get(new_name).content == original
    # ...and the fallback is recorded, not buried.
    assert len(result.degradations) == 1
    deg = result.degradations[0]
    assert deg.stage == PipelineStage.CONTENT_REVISER
    assert deg.kind == "llm_empty_fallback"


def test_unparseable_output_also_degrades_to_prior_notebook(personas_dir, store):
    state = _state_with_notebook(store)
    original = store.get("lesson_notebook_v0").content
    agent = _agent(personas_dir, "not a json array at all")

    result = asyncio.run(agent.run(state, store))

    new_name = result.outputs[-1].artifact_name
    assert store.get(new_name).content == original
    assert result.degradations and result.degradations[0].kind == "llm_empty_fallback"


def test_rewrites_even_with_no_prior_notebook_in_state(personas_dir, store):
    # Defensive: no notebook-producing stage in the outputs and nothing in the store
    # (a degraded/misordered state). The agent falls back to a default name, still
    # produces a notebook from the LLM rewrite, and does not crash.
    state = PipelineState(
        run_id="cr-002",
        current_stage=PipelineStage.CONTENT_REVISER,
        iteration=1,
    )
    agent = _agent(personas_dir, _REWRITE)

    result = asyncio.run(agent.run(state, store))

    new_name = result.outputs[-1].artifact_name
    assert store.has(new_name)
    assert not result.degradations


def test_next_stage_is_executor(personas_dir):
    agent = _agent(personas_dir, _REWRITE)
    assert agent.next_stage() == PipelineStage.EXECUTOR
