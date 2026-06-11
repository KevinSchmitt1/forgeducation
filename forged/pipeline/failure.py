"""Deterministic failure classification for the agentic pipeline.

Reads concrete signals (ExecutionReport, GradeReport) and outputs one of
six FailureCategory values via a flat priority cascade.

Dependency: forged.pipeline.state (Evidence type only).
No LLM calls. Same inputs → same outputs on every run.

Priority cascade (first match wins):
  1. BLOCKER in plan/structure scope  → BLOCKER_STRUCTURE
  2. Execution failed                 → CODE_QUALITY
  3. Code runs but high-severity code finding → TEST_FAILURE
  4. Quality score below threshold    → CONTENT_QUALITY
  5. Execution OK + quality acceptable → ACCEPTABLE
  6. No signals match                 → UNCLASSIFIABLE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .state import Evidence

# ── Categories ─────────────────────────────────────────────────────────────────


class FailureCategory(str, Enum):
    """Deterministic classification of what went wrong in the pipeline.

    Priority ordering matters: the classify() function checks these from top to
    bottom and returns the first match. Changing the order changes behaviour.
    """

    BLOCKER_STRUCTURE = "blocker_structure"   # Lesson structure is wrong → replan
    CODE_QUALITY = "code_quality"             # Code doesn't run → recode
    TEST_FAILURE = "test_failure"             # Code runs but output wrong → recode
    CONTENT_QUALITY = "content_quality"       # Teaching is unclear → revise prose
    ACCEPTABLE = "acceptable"                 # Good enough → terminate
    UNCLASSIFIABLE = "unclassifiable"         # No clear signal → hand to human


# ── Input signals ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionReport:
    """Structured result from the Executor stage.

    ok=True means all cells ran without raising exceptions.
    failed_cells lists zero-based indices of cells that raised.
    error_summary is a short human-readable description of the first error.
    """

    ok: bool
    failed_cells: list[int] = field(default_factory=list)
    error_summary: str | None = None


@dataclass(frozen=True)
class GradeReport:
    """Structured result from the Student (grader) stage.

    quality_score is in [0, 100].
    blockers is a list of free-text blocker descriptions (legacy field; prefer findings).
    findings is the structured list of Evidence objects produced by the student.
    """

    quality_score: float
    blockers: list[str] = field(default_factory=list)
    findings: list[Evidence] = field(default_factory=list)


# ── Classification result ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
    """Immutable result of the failure classification logic.

    category: which of the 6 FailureCategory values matched.
    reason: human-readable explanation for the audit trail and routing log.
    matched_signals: list of short strings tracing back to concrete evidence.
                     Always non-empty; used for debugging and audit review.
    """

    category: FailureCategory
    reason: str
    matched_signals: list[str] = field(default_factory=list)


# ── Classifier ─────────────────────────────────────────────────────────────────

_BLOCKER_SCOPES = ("plan", "structure")
_HIGH_CODE_SEVERITIES = ("HIGH", "BLOCKER")


def _has_blocker_in_plan_scope(grade_report: GradeReport) -> Evidence | None:
    """Return the first BLOCKER finding in plan or structure scope, or None.

    Checking plan/structure scope first means we catch concept-ordering
    problems before they cause code failures in later stages.
    """
    for finding in grade_report.findings:
        if finding.severity == "BLOCKER" and finding.scope in _BLOCKER_SCOPES:
            return finding
    return None


def _has_high_severity_code_finding(grade_report: GradeReport) -> Evidence | None:
    """Return the first HIGH/BLOCKER finding scoped to 'code', or None.

    A code-scoped high-severity finding means the notebook runs but produces
    wrong outputs — distinct from execution failures caught by ExecutionReport.
    """
    for finding in grade_report.findings:
        if finding.scope == "code" and finding.severity in _HIGH_CODE_SEVERITIES:
            return finding
    return None


def classify(
    execution_report: ExecutionReport | None,
    grade_report: GradeReport | None,
    quality_threshold: float = 80.0,
) -> Classification:
    """Classify what went wrong using a deterministic priority cascade.

    Args:
        execution_report: Result of running the notebook. None if executor has not run.
        grade_report: Result of student grading. None if grader has not run.
        quality_threshold: Minimum quality_score to classify as ACCEPTABLE.
                           score >= threshold → ACCEPTABLE; below → CONTENT_QUALITY.

    Returns:
        An immutable Classification with category, reason, and matched_signals.

    IMPORTANT: This function is purely deterministic. No LLM calls, no randomness.
               Same inputs → same output, always.
    """
    signals: list[str] = []

    # Priority 1: BLOCKER in plan or structure scope.
    # Concept-ordering errors need replanning, not code fixes — checking this
    # first prevents wasted code-author iterations on a broken plan.
    if grade_report is not None:
        blocker = _has_blocker_in_plan_scope(grade_report)
        if blocker is not None:
            signals.append(f"BLOCKER in {blocker.scope} scope: {blocker.text[:60]}")
            return Classification(
                category=FailureCategory.BLOCKER_STRUCTURE,
                reason=(
                    "Lesson structure has a blocker-level issue "
                    "(concept ordering, prerequisites, or lesson flow). "
                    "The plan must be revised before recoding."
                ),
                matched_signals=signals,
            )

    # Priority 2: Execution failure.
    # If the notebook did not run at all, grading is meaningless.
    # Route back to CodeAuthor regardless of the grade report.
    if execution_report is not None and not execution_report.ok:
        signals.append(f"Execution failed: cells {execution_report.failed_cells}")
        return Classification(
            category=FailureCategory.CODE_QUALITY,
            reason=(
                f"Code failed to run. "
                f"Cells {execution_report.failed_cells} raised errors."
            ),
            matched_signals=signals,
        )

    # Priority 3: Wrong outputs (code runs, result is incorrect).
    # Distinct from execution failure: the notebook runs without crashing
    # but a high-severity code finding indicates wrong computed values.
    if grade_report is not None:
        bad_finding = _has_high_severity_code_finding(grade_report)
        if bad_finding is not None:
            signals.append(
                f"High-severity code finding ({bad_finding.severity}): "
                f"{bad_finding.text[:60]}"
            )
            return Classification(
                category=FailureCategory.TEST_FAILURE,
                reason="Code runs but produces incorrect output.",
                matched_signals=signals,
            )

    # Priority 4: Quality score below threshold.
    # Code is correct but teaching quality is insufficient.
    # Route to Reviser for prose-level improvements.
    if grade_report is not None and grade_report.quality_score < quality_threshold:
        signals.append(
            f"Quality score {grade_report.quality_score} < threshold {quality_threshold}"
        )
        return Classification(
            category=FailureCategory.CONTENT_QUALITY,
            reason=(
                f"Quality score {grade_report.quality_score:.0f} is below "
                f"threshold {quality_threshold:.0f}. Content revision needed."
            ),
            matched_signals=signals,
        )

    # Priority 5: All signals pass.
    # Execution succeeded and quality is at or above threshold.
    if execution_report is not None and execution_report.ok:
        meets_quality = (
            grade_report is None
            or grade_report.quality_score >= quality_threshold
        )
        if meets_quality:
            signals.append("Execution OK and quality acceptable")
            return Classification(
                category=FailureCategory.ACCEPTABLE,
                reason="Code executed successfully and quality is acceptable.",
                matched_signals=signals,
            )

    # Priority 6: Cannot determine the failure.
    # No signal matched any known pattern; escalate to human review.
    signals.append("No clear signals matched")
    return Classification(
        category=FailureCategory.UNCLASSIFIABLE,
        reason="Unable to classify the failure. Manual review required.",
        matched_signals=signals,
    )
