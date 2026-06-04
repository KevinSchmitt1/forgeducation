"""Acceptance gate — the won't-ship-a-regression layer.

The executor *detects* whether generated code runs and the critics *detect* whether
the prose matches reality and teaches well. The gate turns those signals into a
decision: which notebook version is actually fit to ship.

The decision is **graded for teaching quality, binary for facts** (agreed with Kevin):
  * Crucial issues — a failing code cell or a BLOCKER finding — are a HARD floor. Code
    execution is a genuine binary fact, so it is never "graded away".
  * Teaching quality — CONFUSING/NITPICK findings — feeds a 0–100 quality score, and a
    version is "good enough" once it clears `min_quality`. Minor residuals may ship
    (and are surfaced for optional human review); they don't force another loop.

A pipeline may produce several notebook versions (original, revised, …). The gate
keeps the BEST one — fewest/least-severe issues — never a worse one, so a revision is
adopted only when it genuinely improves things. This is structural, not name-based:
versions are discovered from the pipeline shape, so it scales to any number of rounds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .artifacts import ArtifactStore
from .config import PipelineConfig, StageType
from .ledger import has_blocker, parse_findings, quality_score

# A version is "good enough" to ship when it carries no crucial issue AND its
# teaching-quality score clears this bar. Tunable per pipeline via RevisionPolicy.
DEFAULT_MIN_QUALITY = 90


@dataclass(frozen=True)
class NotebookCandidate:
    """One notebook version and the artifacts that judge it.

    `notebook` is the assembled-notebook artifact name; `report` is the executor
    output that ran it; `feedbacks` are the critic critiques grounded on that report
    (student, reviewer, …) — empty when the pipeline has no critic reading the report.
    """

    notebook: str
    report: str
    feedbacks: tuple[str, ...]


@dataclass(frozen=True)
class CandidateResult:
    """A candidate paired with the gate's verdict on it."""

    candidate: NotebookCandidate
    executed_ok: bool
    has_blocker: bool
    quality_score: int
    accepted: bool  # "good enough": no crucial issue AND quality clears the bar

    @property
    def crucial(self) -> bool:
        """Hard-floor problems that must never ship: a failing cell or a BLOCKER."""
        return not self.executed_ok or self.has_blocker


@dataclass(frozen=True)
class GateDecision:
    """The chosen version plus the verdict on every candidate (the audit trail)."""

    chosen: CandidateResult | None
    results: tuple[CandidateResult, ...]

    @property
    def gate_satisfied(self) -> bool:
        """True when the version we ship is itself good enough to pass unattended."""
        return self.chosen is not None and self.chosen.accepted

    @property
    def crucial_open(self) -> bool:
        """The shipped version still carries a crucial issue. The revision loop
        hard-fails on this rather than silently shipping a broken/misleading lesson."""
        return self.chosen is not None and self.chosen.crucial


def notebook_candidates(pipeline: PipelineConfig) -> list[NotebookCandidate]:
    """Discover notebook versions from the pipeline shape, in execution order.

    A version exists wherever an executor stage runs a single notebook input. Its
    critiques are the text LLM stages that read that executor's report.
    """
    candidates: list[NotebookCandidate] = []
    for stage in pipeline.stages:
        if stage.type is StageType.EXECUTOR and len(stage.inputs) == 1:
            candidates.append(
                NotebookCandidate(
                    notebook=stage.inputs[0],
                    report=stage.output,
                    feedbacks=_feedbacks_reading(pipeline, stage.output),
                )
            )
    return candidates


def evaluate_candidates(
    pipeline: PipelineConfig,
    store: ArtifactStore,
    min_quality: int = DEFAULT_MIN_QUALITY,
) -> GateDecision:
    """Judge every notebook version present in `store` and pick the one to ship."""
    results = tuple(
        _evaluate(candidate, store, min_quality)
        for candidate in notebook_candidates(pipeline)
        if store.has(candidate.report)
    )
    return GateDecision(chosen=_select(results), results=results)


def _select(results: tuple[CandidateResult, ...]) -> CandidateResult | None:
    """Keep the best version: prefer no crucial issue, then higher quality, then the
    earliest (so an equal-quality revision never displaces a good original — churn
    without value is avoided)."""
    chosen: CandidateResult | None = None
    for result in results:
        if chosen is None or _rank(result) > _rank(chosen):
            chosen = result
    return chosen


def _rank(result: CandidateResult) -> tuple[int, int]:
    return (0 if result.crucial else 1, result.quality_score)


def _evaluate(
    candidate: NotebookCandidate, store: ArtifactStore, min_quality: int
) -> CandidateResult:
    report = json.loads(store.get(candidate.report).content)
    executed_ok = bool(report.get("ok"))

    findings: tuple = ()
    for feedback in candidate.feedbacks:
        if store.has(feedback):
            findings += parse_findings(store.get(feedback).content)

    blocker = has_blocker(findings)
    score = quality_score(findings)
    crucial = (not executed_ok) or blocker
    return CandidateResult(
        candidate=candidate,
        executed_ok=executed_ok,
        has_blocker=blocker,
        quality_score=score,
        accepted=(not crucial) and score >= min_quality,
    )


def _feedbacks_reading(pipeline: PipelineConfig, report_name: str) -> tuple[str, ...]:
    """Every text critique grounded on a given execution report, in pipeline order."""
    return tuple(
        stage.output
        for stage in pipeline.stages
        if (
            stage.type is StageType.LLM
            and stage.output_kind == "text"
            and report_name in stage.inputs
        )
    )
