"""CodeAuthor sees the notebook it wrote, and may repair it in place (doc 21, C5).

Before this, `_build_user_message` assembled context + plan + revision brief and nothing
else. On a reroute the author received a complaint about cells it could not see, so
writing a fresh notebook from the plan was the only thing available to it — 24, 21, 24 and
26 cells rewritten to repair 8, 1, 3 and 7 (43% of the 2026-08-13 run's tokens).

Two properties matter here and are easy to lose:

  * the notebook only appears when there is something to repair (nothing to patch on the
    first pass, and the prompt is large);
  * a full-notebook response keeps working exactly as before — some repairs cannot be a
    patch, so the author is never forced into a shape it cannot satisfy.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import nbformat
import pytest

from forged.artifacts import Artifact, ArtifactStore
from forged.notebook import build_notebook
from forged.pipeline.agents.code_author import CodeAuthorAgent
from forged.pipeline.state import (
    PipelineStage,
    PipelineState,
    StageOutput,
    create_initial_state,
)

PREVIOUS_CELLS = [
    {"type": "markdown", "source": "# Start Here"},
    {"type": "code", "source": "print('setup ok')"},
    {"type": "code", "source": "broken = '''unterminated"},
]


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.prompts: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str, **kwargs: object) -> str:
        self.prompts.append(user_prompt)
        return self._response


@pytest.fixture
def personas_dir(tmp_path: Path) -> Path:
    d = tmp_path / "personas"
    d.mkdir()
    (d / "code_author.md").write_text("You are the Code Author.", encoding="utf-8")
    return d


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return ArtifactStore(run_dir)


def _state_after_a_failed_attempt(store: ArtifactStore) -> PipelineState:
    """Iteration 1: a notebook exists and a brief complains about it."""
    store.put(Artifact(name="lesson_plan_v0", kind="text", content="# Lesson: Agents"))
    store.put(
        Artifact(
            name="lesson_notebook_v0", kind="notebook", content=build_notebook(PREVIOUS_CELLS)
        )
    )
    store.put(
        Artifact(
            name="revision_brief_v0",
            kind="text",
            content="Cells [2] raised errors. SyntaxError: unterminated string literal",
        )
    )
    state = create_initial_state(run_id="patch-test")
    state = state.with_output(
        StageOutput(stage=PipelineStage.PLANNER, artifact_name="lesson_plan_v0", iteration=0)
    )
    state = state.with_output(
        StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name="lesson_notebook_v0",
            iteration=0,
        )
    )
    # Iteration 1: the brief the author reads is revision_brief_v{iteration - 1}.
    return replace(state, iteration=1)


def _run(agent: CodeAuthorAgent, state: PipelineState, store: ArtifactStore) -> PipelineState:
    return asyncio.get_event_loop().run_until_complete(agent.run(state, store))


def _sources(store: ArtifactStore, name: str) -> list[str]:
    notebook = nbformat.reads(store.get(name).content, as_version=4)
    return [c.source for c in notebook.cells]


# ── the notebook reaches the prompt ───────────────────────────────────────────────


@pytest.mark.unit
def test_the_previous_notebook_is_in_the_prompt_when_there_is_one(
    personas_dir: Path, store: ArtifactStore
) -> None:
    client = _StubClient(json.dumps({"cells": PREVIOUS_CELLS}))
    state = _state_after_a_failed_attempt(store)

    _run(CodeAuthorAgent(personas_dir=personas_dir, llm_client=client), state, store)

    prompt = client.prompts[0]
    assert "broken = '''unterminated" in prompt, "the author must see what it is repairing"
    assert "[cell 2 · code]" in prompt, "cells must carry the indices the brief cites"


@pytest.mark.unit
def test_no_notebook_is_sent_on_the_first_pass(
    personas_dir: Path, store: ArtifactStore
) -> None:
    """Nothing to repair yet, and the prompt is large — do not pay for it."""
    store.put(Artifact(name="lesson_plan_v0", kind="text", content="# Lesson: Agents"))
    state = create_initial_state(run_id="first-pass").with_output(
        StageOutput(stage=PipelineStage.PLANNER, artifact_name="lesson_plan_v0", iteration=0)
    )
    client = _StubClient(json.dumps({"cells": PREVIOUS_CELLS}))

    _run(CodeAuthorAgent(personas_dir=personas_dir, llm_client=client), state, store)

    assert "[cell 0" not in client.prompts[0]


# ── a patch is applied to the previous notebook ───────────────────────────────────


@pytest.mark.unit
def test_a_patch_response_replaces_only_the_named_cell(
    personas_dir: Path, store: ArtifactStore
) -> None:
    patch = {"patch": [{"index": 2, "type": "code", "source": "fixed = 'ok'"}]}
    state = _state_after_a_failed_attempt(store)

    result = _run(
        CodeAuthorAgent(personas_dir=personas_dir, llm_client=_StubClient(json.dumps(patch))),
        state,
        store,
    )

    sources = _sources(store, result.outputs[-1].artifact_name)
    assert sources[2] == "fixed = 'ok'"
    assert sources[0] == "# Start Here", "untouched cells survive"
    assert sources[1] == "print('setup ok')"
    assert len(sources) == 3


@pytest.mark.unit
def test_a_full_notebook_response_still_works(
    personas_dir: Path, store: ArtifactStore
) -> None:
    """The rewrite path is unchanged — this is the regression guard for it."""
    rewritten = [{"type": "markdown", "source": "# Rewritten"}]
    state = _state_after_a_failed_attempt(store)

    result = _run(
        CodeAuthorAgent(
            personas_dir=personas_dir,
            llm_client=_StubClient(json.dumps({"cells": rewritten})),
        ),
        state,
        store,
    )

    assert _sources(store, result.outputs[-1].artifact_name) == ["# Rewritten"]


@pytest.mark.unit
def test_a_patch_naming_a_missing_cell_degrades_honestly(
    personas_dir: Path, store: ArtifactStore
) -> None:
    """A half-applied notebook would be worse than the recorded fallback."""
    patch = {"patch": [{"index": 99, "type": "code", "source": "nope"}]}
    state = _state_after_a_failed_attempt(store)

    result = _run(
        CodeAuthorAgent(personas_dir=personas_dir, llm_client=_StubClient(json.dumps(patch))),
        state,
        store,
    )

    assert result.degradations, "the fallback must be recorded, not silent"


@pytest.mark.unit
def test_a_patch_without_a_previous_notebook_is_not_applied(
    personas_dir: Path, store: ArtifactStore
) -> None:
    """Nothing to patch against on the first pass — degrade rather than invent a base."""
    store.put(Artifact(name="lesson_plan_v0", kind="text", content="# Lesson"))
    state = create_initial_state(run_id="no-base").with_output(
        StageOutput(stage=PipelineStage.PLANNER, artifact_name="lesson_plan_v0", iteration=0)
    )
    patch = {"patch": [{"index": 0, "type": "code", "source": "x = 1"}]}

    result = _run(
        CodeAuthorAgent(personas_dir=personas_dir, llm_client=_StubClient(json.dumps(patch))),
        state,
        store,
    )

    assert result.degradations
