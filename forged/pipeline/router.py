"""Deterministic routing logic for the agentic pipeline.

Maps FailureCategory classifications to target PipelineStages, enforces
per-stage budgets, and produces auditable RoutingDecision entries.

Dependencies: forged.pipeline.state, forged.pipeline.failure only.
No LLM calls. No randomness. Same inputs → same output on every call.

Routing table (from design doc §4):
    ACCEPTABLE        → terminate
    UNCLASSIFIABLE    → terminate
    BLOCKER_STRUCTURE → PLANNER         (if budget allows, else terminate)
    CODE_QUALITY      → CODE_AUTHOR     (if budget allows, else terminate)
    TEST_FAILURE      → CODE_AUTHOR     (if budget allows, else terminate)
    CONTENT_QUALITY   → CONTENT_REVISER (if budget allows, else terminate)

Phase 4: CONTENT_QUALITY now targets the LLM-backed CONTENT_REVISER (which rewrites
the notebook), not the deterministic REVISER node — the old route was a no-op that
never improved prose. REVISER stays the classifier/router node; nothing routes *to*
it as a failure target anymore.

Budget semantics:
    The budget for stage S is the maximum number of times we will ever
    route to S in one pipeline run.  Once state.get_stage_attempt_count(S)
    reaches the budget limit, any further routing to S terminates instead.
    Executor is unlimited (999) because it always runs after code changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .failure import Classification, FailureCategory
from .state import Evidence, PipelineStage, PipelineState, RoutingDecision

# ── Budget configuration ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class RoutingBudget:
    """Maximum routing attempts allowed per stage in one pipeline run.

    Prevents infinite loops.  Defaults reflect practical experience:
      planner         = 2  (replan at most twice)
      code_author     = 3  (recode at most three times)
      student         = 1  (grade once; grading is deterministic)
      reviser         = 1  (legacy; the classifier node is never a routing target)
      content_reviser = 1  (rewrite prose once, then re-grade)
      executor        = unlimited (always runs after code changes; no budget needed)

    Adjust these via RoutingBudget(planner=3, ...) when creating a Router.
    """

    planner: int = 2
    code_author: int = 3
    student: int = 1
    reviser: int = 1
    content_reviser: int = 1

    def can_route_to(self, stage: PipelineStage) -> bool:
        """Return True when the stage has a non-zero budget configured.

        This checks the static budget value, not the current attempt count.
        Use Router.route() for a full budget + attempt-count check.
        """
        if stage == PipelineStage.EXECUTOR:
            return True  # Executor is unlimited; it always follows code changes.
        budget_map: dict[PipelineStage, int] = {
            PipelineStage.PLANNER: self.planner,
            PipelineStage.CODE_AUTHOR: self.code_author,
            PipelineStage.STUDENT: self.student,
            PipelineStage.REVISER: self.reviser,
            PipelineStage.CONTENT_REVISER: self.content_reviser,
        }
        return budget_map.get(stage, 0) > 0


# ── Request / result value objects ────────────────────────────────────────────


@dataclass(frozen=True)
class RoutingRequest:
    """All information the router needs to produce a routing decision.

    Immutable.  Callers (RevisorAgent) build one of these from the current
    pipeline state, the classification result, and the evidence list.
    """

    state: PipelineState
    classification: Classification
    evidence: list[Evidence]


@dataclass(frozen=True)
class RoutingResult:
    """Immutable output of a routing call.

    next_stage is None when the pipeline should terminate.
    routing_decision is None for terminal results (no audit entry needed).
    reason is always set for human-readable explainability.
    """

    next_stage: PipelineStage | None
    should_terminate: bool
    reason: str
    routing_decision: RoutingDecision | None


# ── Internal helpers ──────────────────────────────────────────────────────────

# Maps non-terminal FailureCategory values to their target PipelineStage.
_CATEGORY_TO_STAGE: dict[FailureCategory, PipelineStage] = {
    FailureCategory.BLOCKER_STRUCTURE: PipelineStage.PLANNER,
    FailureCategory.CODE_QUALITY: PipelineStage.CODE_AUTHOR,
    FailureCategory.TEST_FAILURE: PipelineStage.CODE_AUTHOR,
    FailureCategory.CONTENT_QUALITY: PipelineStage.CONTENT_REVISER,
}

# Human-readable termination messages keyed by target stage.
_BUDGET_EXHAUSTED_REASON: dict[PipelineStage, str] = {
    PipelineStage.PLANNER: (
        "Lesson structure needs revision (replan), but planner budget exhausted."
    ),
    PipelineStage.CODE_AUTHOR: (
        "Code needs fixing, but code author budget exhausted."
    ),
    PipelineStage.CONTENT_REVISER: (
        "Content needs revision, but content-reviser budget exhausted."
    ),
}


def _terminate(reason: str) -> RoutingResult:
    """Build a terminal RoutingResult with no next stage."""
    return RoutingResult(
        next_stage=None,
        should_terminate=True,
        reason=reason,
        routing_decision=None,
    )


def _build_decision(
    state: PipelineState,
    target_stage: PipelineStage,
    classification: Classification,
    evidence: list[Evidence],
) -> RoutingDecision:
    """Construct the RoutingDecision audit entry for a non-terminal routing."""
    return RoutingDecision(
        iteration=state.iteration,
        from_stage=state.current_stage,
        to_stage=target_stage,
        classification=classification.category.value,
        reason=classification.reason,
        evidence=evidence,
    )


# ── Router ────────────────────────────────────────────────────────────────────


class Router:
    """Deterministic routing: classification + budget → next stage.

    Invariants:
      - Same state + classification → same result every time (no randomness)
      - Never routes to a stage whose attempt count has reached the budget limit
      - Every non-terminal result carries a populated RoutingDecision
      - Every terminal result carries routing_decision=None
    """

    def __init__(self, budget: RoutingBudget | None = None) -> None:
        self.budget: RoutingBudget = budget if budget is not None else RoutingBudget()

    def route(self, request: RoutingRequest) -> RoutingResult:
        """Route a pipeline state to the appropriate next stage.

        Args:
            request: Encapsulates state, classification, and evidence.

        Returns:
            An immutable RoutingResult with next_stage and audit information.

        Terminal cases return immediately with should_terminate=True.
        Non-terminal cases check the budget before issuing a routing decision;
        exhausted budget also returns a terminal result.
        """
        category = request.classification.category

        if category == FailureCategory.ACCEPTABLE:
            return _terminate(
                f"Notebook is acceptable. {request.classification.reason}"
            )

        if category == FailureCategory.UNCLASSIFIABLE:
            # Preserve the classifier's specific reason (e.g. a structural-hollow
            # explanation) instead of flattening every unclassifiable run to one
            # generic line — the human reading SUMMARY.md needs the detail.
            return _terminate(
                request.classification.reason
                or "Unable to classify the issue. Manual review required."
            )

        target_stage = _CATEGORY_TO_STAGE[category]
        attempt_count = request.state.get_stage_attempt_count(target_stage)
        budget_limit = getattr(self.budget, target_stage.value)

        if attempt_count >= budget_limit:
            reason = _BUDGET_EXHAUSTED_REASON.get(
                target_stage,
                f"Budget exhausted for {target_stage.value}.",
            )
            return _terminate(reason)

        decision = _build_decision(
            state=request.state,
            target_stage=target_stage,
            classification=request.classification,
            evidence=request.evidence,
        )

        return RoutingResult(
            next_stage=target_stage,
            should_terminate=False,
            reason=f"Routing to {target_stage.value}: {request.classification.reason}",
            routing_decision=decision,
        )
