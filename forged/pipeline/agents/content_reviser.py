"""ContentReviserAgent — rewrites a graded notebook's prose when content is too weak.

Persona: personas/reviser.md
Input artifacts: the latest notebook (from code_author or a prior content revision)
                 + revision_brief_v{N-1}.md (the reviser's findings) + lesson_context.
Output artifact: lesson_notebook_v{iteration}.ipynb (kind=notebook — real nbformat JSON)
Next stage: EXECUTOR (so the rewrite is re-run and then re-graded)

This is the target of the CONTENT_QUALITY route and the fix for P1: the agentic
pipeline previously routed CONTENT_QUALITY to a no-op node, so poor explanations
never improved. This agent makes a real LLM call to rewrite the whole notebook from
the student's findings, mirroring CodeAuthorAgent's output/parse shape.

Fallback differs from code_author on purpose. CodeAuthor falls back to a 2-cell stub
because it has nothing yet; the reviser is *editing an existing, gradeable notebook*,
so collapsing to a stub would be a regression. On LLM failure or unparseable output it
**keeps the prior notebook** (re-emitted under the new version) and records a
Degradation — honest, non-destructive, and the bounded loop still terminates via budget.
"""

from __future__ import annotations

import logging
from pathlib import Path

from forged.artifacts import Artifact, ArtifactStore
from forged.notebook import build_notebook, cells_from_json
from forged.pipeline.state import Degradation, PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

_LOG = logging.getLogger(__name__)

# Stages that produce a notebook the reviser can pick up as its input. Ordered by
# recency at the call site (we scan state.outputs in reverse), so the most recent
# notebook — whether freshly authored or already once-revised — is the one revised.
_NOTEBOOK_STAGES = (PipelineStage.CONTENT_REVISER, PipelineStage.CODE_AUTHOR)


class ContentReviserAgent(Agent[AgentOutput]):
    """Rewrites the current notebook's teaching prose from the reviser's findings."""

    def __init__(self, personas_dir: Path | None = None, llm_client=None) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)

    def _load_persona(self) -> str:
        path = self.personas_dir / "reviser.md"
        return path.read_text(encoding="utf-8")

    def next_stage(self) -> PipelineStage:
        return PipelineStage.EXECUTOR

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        source_name = self._latest_notebook_name(state)
        prior_notebook = store.get(source_name).content if store.has(source_name) else "[]"
        artifact_name = f"lesson_notebook_v{state.iteration}"

        degradation: Degradation | None = None
        try:
            response = self._call_llm(state, store, source_name, artifact_name)
        except RuntimeError as exc:
            # Non-destructive fallback: keep the gradeable notebook rather than a stub.
            _LOG.warning("ContentReviserAgent fell back to the prior notebook: %s", exc)
            response = prior_notebook
            degradation = Degradation(
                stage=PipelineStage.CONTENT_REVISER, kind="llm_empty_fallback", detail=str(exc)
            )

        store.put(Artifact(name=artifact_name, kind="notebook", content=response))
        output = StageOutput(
            stage=PipelineStage.CONTENT_REVISER,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        new_state = state.with_output(output)
        if degradation is not None:
            new_state = new_state.with_degradation(degradation)
        return new_state.with_current_stage(self.next_stage())

    def _call_llm(
        self,
        state: PipelineState,
        store: ArtifactStore,
        source_name: str,
        output_artifact: str,
    ) -> str:
        """Call the LLM and return assembled nbformat JSON. Raises RuntimeError on
        an empty/unparseable response so run() can fall back to the prior notebook."""
        user_msg = self._build_user_message(state, store, source_name)
        input_artifacts: tuple[str, ...] = (source_name,)
        brief_name = f"revision_brief_v{state.iteration - 1}"
        if store.has(brief_name):
            input_artifacts = (*input_artifacts, brief_name)
        raw = self._complete_llm(
            stage_name=PipelineStage.CONTENT_REVISER,
            state=state,
            store=store,
            user_msg=user_msg,
            input_artifacts=input_artifacts,
            output_artifact=output_artifact,
        )
        return self._parse_cells(raw)

    def _parse_cells(self, raw: str) -> str:
        """Validate the model's cell list and assemble a real .ipynb. Mirrors
        CodeAuthorAgent: raises RuntimeError on malformed output."""
        try:
            cells = cells_from_json(raw)
        except ValueError as exc:
            raise RuntimeError(f"ContentReviserAgent: {exc}") from exc
        return build_notebook(cells)

    def _build_user_message(
        self, state: PipelineState, store: ArtifactStore, source_name: str
    ) -> str:
        notebook = store.get(source_name).content if store.has(source_name) else "(no notebook)"
        parts = [f"Current notebook (rewrite this in full):\n{notebook}"]
        brief_name = f"revision_brief_v{state.iteration - 1}"
        if store.has(brief_name):
            parts.append(f"Student feedback to address:\n{store.get(brief_name).content}")
        return self._context_prefix(store) + "\n\n".join(parts)

    def _latest_notebook_name(self, state: PipelineState) -> str:
        """The most recent notebook to revise (from code_author or a prior revision)."""
        for output in reversed(state.outputs):
            if output.stage in _NOTEBOOK_STAGES:
                return output.artifact_name
        return f"lesson_notebook_v{state.iteration}"
