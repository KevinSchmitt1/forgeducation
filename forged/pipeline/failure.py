"""Deterministic failure classification for the agentic pipeline.

Reads concrete signals (ExecutionReport, GradeReport) and outputs one of
six FailureCategory values via a flat priority cascade.

Dependency: forged.pipeline.state (Evidence type only).
No LLM calls. Same inputs → same outputs on every run.

Priority cascade (first match wins):
  1. BLOCKER in plan/structure scope  → BLOCKER_STRUCTURE
  2. Execution failed                 → CODE_QUALITY
  3. Grader ran but produced no usable grade → UNCLASSIFIABLE
  4. Code runs but high-severity code finding → TEST_FAILURE
  5. Quality score below threshold    → CONTENT_QUALITY
  6a. Execution OK + quality OK but structurally hollow → UNCLASSIFIABLE
  6b. Execution OK + quality acceptable → ACCEPTABLE
  7. No signals match                 → UNCLASSIFIABLE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .state import Evidence
from .structure import StructuralReport

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


# Canonical rubric dimension names. The single source of truth — student.py and
# reviser.py import this rather than redefining the tuple, so adding a dimension
# is a one-line change that can never drift out of sync across modules.
RUBRIC_DIMENSIONS = (
    "structure",
    "explanation_depth",
    "code_clarity",
    "correctness",
    "learner_fit",
)


@dataclass(frozen=True)
class RubricScores:
    """Per-dimension teaching-quality scores from the Student grader.

    Each dimension is in [0, 100]:
      structure          — concept ordering and lesson flow
      explanation_depth  — are the explanations real and sufficient, not stubs?
      code_clarity       — is the code readable and understandable for this learner?
      correctness        — does the code do what the prose claims (anti-bug)?
      learner_fit        — pitched right for the profile (not too shallow/deep)?

    composite() is the equal-weighted mean. When the student produces a rubric it
    sets GradeReport.quality_score to this composite, so the routing threshold is
    driven by the five concrete dimensions rather than an opaque standalone number.
    The dimensions are also surfaced individually in revision briefs so a rerouted
    agent can target the specific weakness.
    """

    structure: float
    explanation_depth: float
    code_clarity: float
    correctness: float
    learner_fit: float

    def composite(self) -> float:
        """Equal-weighted mean of the five dimensions, in [0, 100]."""
        values = [getattr(self, dim) for dim in RUBRIC_DIMENSIONS]
        return sum(values) / len(values)


@dataclass(frozen=True)
class GradeReport:
    """Structured result from the Student (grader) stage.

    quality_score is in [0, 100] — the composite the routing threshold reads.
    rubric carries the per-dimension breakdown when the student produced one.
    graded is False when the student could not produce a usable assessment
    (e.g. its LLM call failed); a False grade is an *absence* of signal, not a
    low score, and the classifier treats it as UNCLASSIFIABLE rather than poor
    content — a failed grader must never masquerade as "mediocre teaching".
    blockers is a list of free-text blocker descriptions (legacy field; prefer findings).
    findings is the structured list of Evidence objects produced by the student.
    """

    quality_score: float
    rubric: RubricScores | None = None
    graded: bool = True
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
    structural_report: StructuralReport | None = None,
) -> Classification:
    """Classify what went wrong using a deterministic priority cascade.

    Args:
        execution_report: Result of running the notebook. None if executor has not run.
        grade_report: Result of student grading. None if grader has not run.
        quality_threshold: Minimum quality_score to classify as ACCEPTABLE.
                           score >= threshold → ACCEPTABLE; below → CONTENT_QUALITY.
        structural_report: Deterministic anti-hollow check on the executed notebook.
                           Only consulted at the ACCEPTABLE gate: a notebook that
                           would otherwise pass but is structurally hollow (all
                           cells skipped, no worked example) is refused.

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

    # Priority 3: Grading failed — the notebook ran but the student could not
    # produce a usable assessment. This is an ABSENCE of signal, not a low score:
    # we genuinely do not know the teaching quality. Escalate to human review
    # rather than letting a failed grader masquerade as "mediocre content" and
    # burn a no-op reviser lap. (grade_report is None — grader not run yet — is a
    # different case, handled as ACCEPTABLE below when execution is clean.)
    if grade_report is not None and not grade_report.graded:
        signals.append("Student grading failed; quality could not be assessed")
        return Classification(
            category=FailureCategory.UNCLASSIFIABLE,
            reason=(
                "The student grader did not return a usable assessment, so the "
                "lesson's teaching quality could not be judged. Manual review required."
            ),
            matched_signals=signals,
        )

    # Priority 4: Wrong outputs (code runs, result is incorrect).
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

    # Priority 5: Quality score below threshold.
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

    # Priority 6: All signals pass.
    # Execution succeeded; reaching here means quality is acceptable too — priority 5
    # already returned for any below-threshold grade, so no quality re-check is needed.
    if execution_report is not None and execution_report.ok:
        # Anti-hollow backstop: a green, well-graded notebook that nonetheless
        # demonstrates nothing (all cells skipped behind dep guards) must not ship
        # as ACCEPTABLE. This is the deterministic catch for when the LLM student
        # wrongly passes a hollow lesson. Terminate for review rather than loop —
        # replanning cannot conjure the missing runtime.
        if structural_report is not None and structural_report.is_hollow:
            detail = "; ".join(structural_report.reasons)
            signals.append(f"Notebook is structurally hollow: {detail}")
            return Classification(
                category=FailureCategory.UNCLASSIFIABLE,
                reason=(
                    "Notebook executed cleanly but does not actually demonstrate "
                    f"the lesson: {detail}. Manual review required."
                ),
                matched_signals=signals,
            )
        signals.append("Execution OK and quality acceptable")
        return Classification(
            category=FailureCategory.ACCEPTABLE,
            reason="Code executed successfully and quality is acceptable.",
            matched_signals=signals,
        )

    # Priority 7: Cannot determine the failure.
    # No signal matched any known pattern; escalate to human review.
    signals.append("No clear signals matched")
    return Classification(
        category=FailureCategory.UNCLASSIFIABLE,
        reason="Unable to classify the failure. Manual review required.",
        matched_signals=signals,
    )
