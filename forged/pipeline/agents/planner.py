"""PlannerAgent — produces a lesson plan from a topic brief and learner profile.

Persona: personas/planner.md
Input artifacts: (none required; reads from state metadata or uses defaults)
Output artifact: lesson_plan_v{iteration}.md  (kind=text)
Next stage: CODE_AUTHOR

Phase 8: When rerouted from Reviser, reads revision_brief_v{N}.md to understand
what structural or pedagogical issues need fixing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.state import PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

_LOG = logging.getLogger(__name__)


class PlannerAgent(Agent[AgentOutput]):
    """Turns a topic brief into a structured lesson plan.

    Reads personas/planner.md as the system prompt and calls the configured
    LLM backend to generate the plan.
    """

    def __init__(self, personas_dir: Path | None = None, llm_client=None) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)

    def _load_persona(self) -> str:
        path = self.personas_dir / "planner.md"
        return path.read_text(encoding="utf-8")

    def next_stage(self) -> PipelineStage:
        return PipelineStage.CODE_AUTHOR

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        user_msg = self._build_user_message(state, store)
        artifact_name = f"lesson_plan_v{state.iteration}"
        try:
            response = self._call_llm(state, store, user_msg, artifact_name)
        except RuntimeError as exc:
            raise RuntimeError(f"PlannerAgent LLM call failed: {exc}") from exc
        store.put(Artifact(name=artifact_name, kind="text", content=response))
        output = StageOutput(
            stage=PipelineStage.PLANNER,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(self.next_stage())

    def _call_llm(
        self,
        state: PipelineState,
        store: ArtifactStore,
        user_msg: str,
        output_artifact: str,
    ) -> str:
        """Call the LLM with the planner system prompt and return the text response."""
        input_artifacts = ("brief",) if store.has("brief") else ()
        if self._read_revision_brief(state, store):
            input_artifacts = (*input_artifacts, f"revision_brief_v{state.iteration - 1}")
        return self._complete_llm(
            stage_name=PipelineStage.PLANNER,
            state=state,
            store=store,
            user_msg=user_msg,
            input_artifacts=input_artifacts,
            output_artifact=output_artifact,
        )

    def _build_user_message(self, state: PipelineState, store: ArtifactStore) -> str:
        lines = [f"Run ID: {state.run_id}", f"Iteration: {state.iteration}"]
        if store.has("brief"):
            lines.append(f"\nBrief:\n{store.get('brief').content}")
        revision_brief = self._read_revision_brief(state, store)
        if revision_brief:
            lines.append(f"\nFeedback from previous attempt:\n{revision_brief}")
        return self._context_prefix(store) + "\n".join(lines)

    def _read_revision_brief(self, state: PipelineState, store: ArtifactStore) -> str:
        """Read revision_brief artifact if available (feedback from reviser)."""
        brief_name = f"revision_brief_v{state.iteration - 1}"
        if store.has(brief_name):
            try:
                return store.get(brief_name).content
            except Exception as exc:
                _LOG.warning("Failed to read revision brief %s: %s", brief_name, exc)
        return ""
