"""CodeAuthorAgent — produces notebook cells from a lesson plan.

Persona: personas/code_author.md
Input artifacts: lesson_plan_v{N}.md  (reads latest from outputs)
Output artifact: lesson_notebook_v{iteration}.ipynb  (kind=notebook — real
nbformat JSON, assembled from the model's cell list via forged.notebook)
Next stage: EXECUTOR

The stored artifact MUST be valid nbformat: the executor reads it back with
nbformat.reads(). The model only ever produces the simple cell-list format;
assembly into .ipynb happens here, exactly as in the linear LLMAgent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from forged.artifacts import Artifact, ArtifactStore
from forged.notebook import build_notebook, cells_from_json
from forged.pipeline.state import PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

_LOG = logging.getLogger(__name__)

# Fallback cells used when the LLM response cannot be parsed as a JSON array.
_FALLBACK_CELLS = [
    {"type": "markdown", "source": "# Lesson\n\nIntroduction to the topic."},
    {
        "type": "code",
        "source": (
            "# Setup check — run me first\n"
            "import sys\n"
            'print("Setup OK — Python", sys.version.split()[0])'
        ),
    },
]


class CodeAuthorAgent(Agent[AgentOutput]):
    """Converts a lesson plan into a runnable Jupyter notebook.

    Reads the most recent lesson_plan artifact from the store and builds
    notebook cells by calling the configured LLM backend.
    """

    def __init__(self, personas_dir: Path | None = None, llm_client=None) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)

    def _load_persona(self) -> str:
        path = self.personas_dir / "code_author.md"
        return path.read_text(encoding="utf-8")

    def next_stage(self) -> PipelineStage:
        return PipelineStage.EXECUTOR

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        user_msg = self._build_user_message(state, store)
        try:
            response = self._call_llm(user_msg)
        except RuntimeError as exc:
            _LOG.warning("CodeAuthorAgent LLM call failed, using fallback cells: %s", exc)
            response = build_notebook(_FALLBACK_CELLS)
        artifact_name = f"lesson_notebook_v{state.iteration}"
        store.put(Artifact(name=artifact_name, kind="notebook", content=response))
        output = StageOutput(
            stage=PipelineStage.CODE_AUTHOR,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(self.next_stage())

    def _call_llm(self, user_msg: str) -> str:
        """Call the LLM and return assembled nbformat notebook JSON."""
        raw = self._llm_client.complete(self.persona, user_msg)
        return self._parse_cells(raw)

    def _parse_cells(self, raw: str) -> str:
        """Validate the model's cell list and assemble a real .ipynb from it.

        cells_from_json strips ```json fences, accepts a bare array or a
        {"cells": [...]} object, and validates every cell. The result is
        serialized nbformat JSON — the format the executor reads back.
        Raises RuntimeError on malformed output so run() can fall back.
        """
        try:
            cells = cells_from_json(raw)
        except ValueError as exc:
            raise RuntimeError(f"CodeAuthorAgent: {exc}") from exc
        return build_notebook(cells)

    def _build_user_message(self, state: PipelineState, store: ArtifactStore) -> str:
        plan_name = self._latest_plan_name(state)
        plan_content = (
            store.get(plan_name).content if store.has(plan_name) else "(no plan available)"
        )
        profile_content = store.get("profile").content if store.has("profile") else ""
        parts = [f"Lesson Plan:\n{plan_content}"]
        if profile_content:
            parts.append(f"Learner Profile:\n{profile_content}")
        revision_brief = self._read_revision_brief(state, store)
        if revision_brief:
            parts.append(f"Feedback from previous attempt:\n{revision_brief}")
        return "\n\n".join(parts)

    def _latest_plan_name(self, state: PipelineState) -> str:
        for output in reversed(state.outputs):
            if output.stage == PipelineStage.PLANNER:
                return output.artifact_name
        return f"lesson_plan_v{state.iteration}"

    def _read_revision_brief(self, state: PipelineState, store: ArtifactStore) -> str:
        """Read revision_brief artifact if available (feedback from reviser)."""
        brief_name = f"revision_brief_v{state.iteration - 1}"
        if store.has(brief_name):
            try:
                return store.get(brief_name).content
            except Exception as exc:
                _LOG.warning("Failed to read revision brief %s: %s", brief_name, exc)
        return ""
