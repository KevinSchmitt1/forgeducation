"""Immutable state schema for the agentic pipeline.

PipelineState flows through every LangGraph node unchanged;
builders return new instances — never mutate in place.

Dependency: stdlib only (dataclasses, enum, uuid, typing).
No imports from other pipeline modules; state is the foundation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal

# ── Enums ──────────────────────────────────────────────────────────────────────


class PipelineStage(str, Enum):
    """Stages in the agentic pipeline, in execution order."""

    PLANNER = "planner"
    CODE_AUTHOR = "code_author"
    EXECUTOR = "executor"
    STUDENT = "student"
    REVISER = "reviser"


class LocationType(str, Enum):
    """Where a finding or issue is anchored within the lesson."""

    CELL = "cell"
    SECTION = "section"
    LESSON_STRUCTURE = "lesson_structure"
    ARTIFACT = "artifact"
    GLOBAL = "global"


# ── Value objects ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Location:
    """Precise anchor for a finding within the lesson.

    CELL type requires cell_index; all other types must omit it.

    Examples:
        Location(type=LocationType.CELL, cell_index=5, label="hash lookup")
        Location(type=LocationType.SECTION, label="Complexity discussion")
        Location(type=LocationType.GLOBAL)
    """

    type: LocationType
    cell_index: int | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if self.type == LocationType.CELL and self.cell_index is None:
            raise ValueError("CELL location must have cell_index")
        if self.type != LocationType.CELL and self.cell_index is not None:
            raise ValueError(
                f"{self.type.value} location should not have cell_index"
            )


# Shared vocabularies for Evidence — import these wherever findings are built
# so producers and the classifier can never drift apart.
Severity = Literal["BLOCKER", "HIGH", "MEDIUM", "LOW"]
Scope = Literal["plan", "code", "content", "structure", "unknown"]


@dataclass(frozen=True)
class Evidence:
    """A concrete signal that informs a routing decision.

    Severity and scope enable downstream agents to understand impact
    without re-reading the full report.
    """

    source: str
    severity: Severity
    scope: Scope
    location: Location
    text: str


@dataclass(frozen=True)
class RoutingDecision:
    """One routing event in the audit trail.

    A new entry is appended each time the Reviser decides where to route next.
    timestamp uses UUID4 so it is unique and sortable per session without
    a real clock (avoids test flakiness from time-based collisions).
    """

    iteration: int
    from_stage: PipelineStage
    to_stage: PipelineStage | None
    classification: str
    reason: str
    evidence: list[Evidence] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class StageOutput:
    """One stage's contribution to the pipeline.

    artifact_name is the key used to retrieve content from ArtifactStore.
    data carries optional stage-specific metadata (e.g., quality scores).
    """

    stage: PipelineStage
    artifact_name: str
    iteration: int
    data: dict | None = None


# ── Main state ─────────────────────────────────────────────────────────────────


@dataclass
class PipelineState:
    """Immutable-by-convention state flowing through the LangGraph.

    Never mutate this object directly. Use the `with_*` builders,
    each of which returns a fresh PipelineState via dataclasses.replace().

    Invariants enforced at construction:
      - current_stage must be a PipelineStage instance
      - iteration must be >= 0
    """

    run_id: str
    current_stage: PipelineStage
    iteration: int

    outputs: list[StageOutput] = field(default_factory=list)
    stage_attempts: dict[str, int] = field(default_factory=dict)
    routing_log: list[RoutingDecision] = field(default_factory=list)

    is_terminal: bool = False
    terminal_reason: str | None = None
    # True only when the pipeline ended because the notebook was ACCEPTABLE.
    # Errors, budget exhaustion, and unclassifiable runs are terminal but not ok.
    terminal_ok: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.current_stage, PipelineStage):
            raise TypeError(
                f"current_stage must be PipelineStage, got {type(self.current_stage)}"
            )
        if self.iteration < 0:
            raise ValueError(
                f"iteration must be >= 0, got {self.iteration}"
            )

    # ── Builders ────────────────────────────────────────────────────────────

    def with_current_stage(self, stage: PipelineStage) -> PipelineState:
        """Return a new state with a different current stage."""
        return replace(self, current_stage=stage)

    def with_output(self, output: StageOutput) -> PipelineState:
        """Return a new state with one additional stage output appended.

        Creates a new list to preserve immutability of the original.
        """
        return replace(self, outputs=self.outputs + [output])

    def with_routing_decision(self, decision: RoutingDecision) -> PipelineState:
        """Return a new state with a routing decision appended and iteration bumped.

        Iteration increments on every routing event so each loop pass
        can be distinguished in artifact names.
        """
        return replace(
            self,
            routing_log=self.routing_log + [decision],
            iteration=self.iteration + 1,
        )

    def with_attempt(self, stage: PipelineStage) -> PipelineState:
        """Return a new state with the attempt counter for a stage incremented.

        Creates a new dict to preserve immutability of the original.
        """
        current = self.stage_attempts.get(stage.value, 0)
        updated = {**self.stage_attempts, stage.value: current + 1}
        return replace(self, stage_attempts=updated)

    def with_terminal(self, reason: str, ok: bool = False) -> PipelineState:
        """Return a new state marked as terminal (pipeline complete).

        Args:
            reason: Human-readable termination cause, e.g.
                    "acceptable", "budget_exhausted", "unclassifiable".
            ok: True only when termination means success (notebook acceptable).
                Defaults to False so error paths can never accidentally report
                success by omitting the flag.
        """
        return replace(self, is_terminal=True, terminal_reason=reason, terminal_ok=ok)

    # ── Queries ─────────────────────────────────────────────────────────────

    def get_stage_attempt_count(self, stage: PipelineStage) -> int:
        """How many times has this stage been attempted in this run?"""
        return self.stage_attempts.get(stage.value, 0)

    def last_routing_to_stage(self, stage: PipelineStage) -> RoutingDecision | None:
        """The most recent routing decision that sent the pipeline to this stage.

        Returns None when the stage has never been targeted.
        Iterating in reverse keeps complexity O(n) but returns the latest entry.
        """
        for decision in reversed(self.routing_log):
            if decision.to_stage == stage:
                return decision
        return None


# ── Factory ────────────────────────────────────────────────────────────────────


def create_initial_state(run_id: str | None = None) -> PipelineState:
    """Create a fresh pipeline state ready for the Planner.

    Args:
        run_id: Unique run identifier. Generates a UUID when omitted.

    Returns:
        A new PipelineState at iteration 0, stage PLANNER, with no outputs.
    """
    return PipelineState(
        run_id=run_id if run_id is not None else str(uuid.uuid4()),
        current_stage=PipelineStage.PLANNER,
        iteration=0,
    )
