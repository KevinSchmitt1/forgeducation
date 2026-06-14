"""Agent protocol for the agentic pipeline.

Defines the abstract base class that every concrete agent must implement,
the AgentOutput value object, and a PlannerAgent stub for testing and
early integration work.

Persona loading contract:
  - Each Agent subclass reads its persona from a .md file in personas_dir.
  - Loading happens immediately in __init__ (fail-fast: FileNotFoundError
    is raised at construction time, not at run time).
  - personas_dir defaults to Path("personas") relative to the caller's cwd.

Imports only from: forged.pipeline.state — no circular imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar

from ..state import PipelineStage, PipelineState

if TYPE_CHECKING:
    from forged.artifacts import ArtifactStore
    from forged.llm import LLMClient


# ── Type variable ──────────────────────────────────────────────────────────────

T = TypeVar("T")


# ── Agent base class ───────────────────────────────────────────────────────────


class Agent(ABC, Generic[T]):
    """Abstract base class for all pipeline agents.

    CONTRACT:
      - Subclasses must implement _load_persona(), run(), and next_stage().
      - Persona is loaded during __init__; a missing file raises FileNotFoundError.
      - run() must never mutate the input state; it must return a new PipelineState.
      - next_stage() returns the stage that follows, or None for terminal agents.

    PERSONA LOADING:
      - _load_persona() is called inside __init__ and the result stored as self.persona.
      - Each subclass reads personas_dir / "<name>.md" and returns the raw text.
      - If the file is missing, the FileNotFoundError propagates immediately so
        callers learn about misconfiguration at startup, not mid-pipeline.
    """

    def __init__(
        self,
        personas_dir: Path | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        from forged.config import ModelConfig
        from forged.llm import LLMClient as _LLMClient  # local import avoids circular-import risk
        self.personas_dir: Path = Path("personas") if personas_dir is None else Path(personas_dir)
        self.persona: str = self._load_persona()
        self._llm_client: LLMClient = (
            llm_client if llm_client is not None else _LLMClient(ModelConfig())
        )

    @abstractmethod
    def _load_persona(self) -> str:
        """Load this agent's persona text from personas_dir.

        Each concrete agent reads a specific file, e.g.:
            return (self.personas_dir / "planner.md").read_text(encoding="utf-8")

        Raises:
            FileNotFoundError: When the persona file is absent.

        Returns:
            Full text of the persona file as a str.
        """

    @abstractmethod
    async def run(
        self,
        state: PipelineState,
        store: ArtifactStore,
    ) -> PipelineState:
        """Execute this agent and return an updated state.

        Args:
            state: Current pipeline state. Treat as read-only.
            store: Artifact store for reading inputs and writing outputs.

        Returns:
            A new PipelineState with this agent's output appended.
        """

    @abstractmethod
    def next_stage(self) -> PipelineStage | None:
        """Return the pipeline stage that follows this agent.

        Returns None for terminal agents (e.g. Reviser, which uses the
        router to determine routing dynamically).
        """

    def _context_prefix(self, store: ArtifactStore) -> str:
        """Return the shared learner + topic context block as a prompt prefix.

        Both pipelines store the rendered block under the `lesson_context`
        artifact (see forged.context). Returns '' when no context was supplied,
        so an agent can prepend it to its user message unconditionally.
        """
        if store.has("lesson_context"):
            block = store.get("lesson_context").content
            if block:
                return f"{block}\n\n"
        return ""

    def _complete_llm(
        self,
        *,
        stage_name: PipelineStage,
        state: PipelineState,
        store: ArtifactStore,
        user_msg: str,
        input_artifacts: tuple[str, ...],
        output_artifact: str,
    ) -> str:
        from forged.llm import LLMTraceContext

        artifact_names = list(input_artifacts)
        if store.has("lesson_context") and "lesson_context" not in artifact_names:
            artifact_names.insert(0, "lesson_context")

        return self._llm_client.complete(
            self.persona,
            user_msg,
            trace_context=LLMTraceContext(
                stage_name=stage_name.value,
                pipeline_kind="agentic",
                run_id=state.run_id,
                run_dir=str(store.run_dir),
                pipeline_name="agentic",
                iteration=state.iteration,
                input_artifacts=tuple(artifact_names),
                output_artifact=output_artifact,
            ),
        )


# ── AgentOutput value object ───────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentOutput:
    """Immutable output descriptor produced by an agent after run().

    stage_name: which agent produced this (e.g. "planner").
    artifact_name: key used to retrieve content from ArtifactStore.
    artifact_kind: coarse content type ("text", "notebook", "json").
    metadata: optional stage-specific data (token counts, scores, etc.).
    """

    stage_name: str
    artifact_name: str
    artifact_kind: str
    metadata: dict | None = None


from .planner import PlannerAgent  # noqa: E402  (bottom import avoids circular dependency)

__all__ = [
    "Agent",
    "AgentOutput",
    "PlannerAgent",
]
