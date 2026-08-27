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
  4b. Goal-fit verdict reports drift  → BLOCKER_STRUCTURE
  4c. A rubric dimension below the fatal floor → TEST_FAILURE (correctness)
                                              or CONTENT_QUALITY (teaching)
  4d. Goal-fit verdict reports a shape problem → CONTENT_QUALITY
  5. Quality score below threshold    → CONTENT_QUALITY
  6a. Execution OK + quality OK but structurally hollow → UNCLASSIFIABLE
  6b. Execution OK + quality acceptable → ACCEPTABLE
  7. No signals match                 → UNCLASSIFIABLE

Ordering note for 4b–4d: drift is checked *above* the rubric because fixing code in a
lesson that teaches the wrong subject throws the fix away, while a shape problem
("too much machinery") is checked *below* it because broken code is repaired before
the lesson is trimmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .mode import LessonMode
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


# The score below which a single dimension is fatal on its own, no matter what the
# mean says (docs/architecture/22-review-that-points-at-the-fix.md → D1/R1).
#
# Calibrated against the one real case we have. Iteration v1 of the 2026-08-13
# artifact run scored `correctness` 70 — "the validator run fails, the learner cannot
# finish" — alongside four dimensions at 80–90, for a composite of 82: the highest
# mark of the run, awarded to a notebook that produced no artifacts at all. With the
# acceptance threshold at 80, a dimension sitting more than a few points below the bar
# is precisely what four healthy dimensions can outvote, so the floor is set just
# above that case rather than at a round number chosen for its looks.
FATAL_DIMENSION_FLOOR = 75.0

# Dimensions the fatal gate treats as a *code* defect rather than a teaching one.
# `correctness` asks "does the code do what the prose claims" — when that is what
# failed, rewriting the prose cannot fix it, so the lesson goes back to the author.
_CODE_DIMENSIONS = ("correctness",)


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

    def fatal_dimensions(
        self, floor: float = FATAL_DIMENSION_FLOOR
    ) -> tuple[str, ...]:
        """Dimensions scoring below `floor`, in canonical RUBRIC_DIMENSIONS order.

        Deliberately kept *beside* composite() rather than folded into it: the mean
        stays comparable across runs, and the fatal condition is read as its own
        signal instead of being averaged away — which is the whole point of the gate.
        """
        return tuple(dim for dim in RUBRIC_DIMENSIONS if getattr(self, dim) < floor)


# The goal-fit vocabulary (docs/architecture/22-review-that-points-at-the-fix.md → D6/R5).
# Canonical order — merged verdicts are reported in it, and `drifted` leads because it
# is the one that changes the route.
#
#   drifted      — the code does not serve the objective the plan named
#   overwhelming — more machinery than the learner needs to reach that objective
#   insufficient — trimmed past the point where it still teaches
#
# `overwhelming` and `insufficient` are two directions of one axis, deliberately not two
# scores: a lesson can be both at once (the 2026-08-13 run was), and a grader forced to
# pick a direction says "fine".
GOAL_FIT_PROBLEMS = ("drifted", "overwhelming", "insufficient")

# The only problem that reaches the planner. Kept as its own name so the routing rule
# reads as a rule rather than as a string comparison buried in the cascade.
_PLAN_SCOPE_GOAL_FIT = "drifted"


def goal_fit_schema(allowed_problems: tuple[str, ...] = GOAL_FIT_PROBLEMS) -> dict:
    """The JSON-schema fragment both graders use to emit a goal-fit verdict.

    Lives here, beside the vocabulary it constrains, so the enum a grader is offered
    and the enum the classifier acts on can never drift apart. `allowed_problems`
    narrows it per critic: the Student is not offered `drifted` at all, because drift
    is the expert Reviewer's call and the one problem that routes to the planner.
    """
    return {
        "type": ["object", "null"],
        "properties": {
            "fit": {"type": "boolean"},
            "problems": {
                "type": "array",
                "items": {"type": "string", "enum": list(allowed_problems)},
            },
            "text": {"type": "string"},
        },
        "required": ["fit", "problems", "text"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class GoalFitVerdict:
    """Does the code in this lesson earn its place?

    The rubric's five dimensions all ask how well the code that exists is *presented*.
    None asks whether it should exist — the founding complaint of this project (doc 18:
    code-heavy, not practical). This verdict is that question, and it lives **beside**
    the rubric rather than inside it: averaging is what hid the fatal condition in D1,
    so the fix must not be more arithmetic, and a sixth dimension would make every
    historical composite incomparable.

    fit      — False when at least one critic refuses the lesson on these grounds.
    problems — zero or more of GOAL_FIT_PROBLEMS, in canonical order.
    text     — the critic's own words, carried into the revision brief. A verdict the
               next agent cannot act on is not worth collecting.
    """

    fit: bool
    problems: tuple[str, ...] = ()
    text: str = ""

    def merged_with(self, other: GoalFitVerdict | None) -> GoalFitVerdict:
        """Combine the two critics' verdicts into the one the classifier reads.

        Fit requires both to grant it; problems are the union; both rationales are
        kept, because which critic objected is itself information for the next agent.
        Returns a new verdict — neither input is touched.
        """
        if other is None:
            return self
        problems = tuple(
            p for p in GOAL_FIT_PROBLEMS if p in self.problems or p in other.problems
        )
        texts = [t for t in (self.text, other.text) if t]
        return GoalFitVerdict(
            fit=self.fit and other.fit,
            problems=problems,
            text=" | ".join(texts),
        )


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
    goal_fit is the critics' merged answer to "does this code earn its place?" (R5).
    None means no critic produced one — an absent judgement, never a negative one, so
    a provider that cannot emit it keeps the previous behaviour exactly.
    """

    quality_score: float
    rubric: RubricScores | None = None
    graded: bool = True
    blockers: list[str] = field(default_factory=list)
    findings: list[Evidence] = field(default_factory=list)
    goal_fit: GoalFitVerdict | None = None


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


def _classify_goal_fit_drift(grade_report: GradeReport) -> Classification | None:
    """Priority 4b: the lesson teaches the wrong subject → replan.

    Checked above the rubric because repairing code inside a drifted lesson throws
    the repair away. This is the one goal-fit problem that reaches the planner, and
    by construction only the expert Reviewer can raise it — see
    `RevisorAgent._coerce_goal_fit(allow_drift=...)`.
    """
    verdict = grade_report.goal_fit
    if verdict is None or verdict.fit or _PLAN_SCOPE_GOAL_FIT not in verdict.problems:
        return None
    return Classification(
        category=FailureCategory.BLOCKER_STRUCTURE,
        reason=(
            "The lesson does not serve the objective the plan named — the subject "
            f"itself has drifted: {verdict.text}"
        ),
        matched_signals=[f"Goal-fit verdict: drifted — {verdict.text[:80]}"],
    )


def _classify_fatal_dimension(
    grade_report: GradeReport, fatal_floor: float
) -> Classification | None:
    """Priority 4c: a single rubric dimension is fatal on its own.

    The composite is a mean, so four healthy dimensions can outvote one fatal one —
    the 2026-08-13 run awarded 82/100 to a notebook that produced nothing (doc 22,
    D1). Read the dimension directly rather than trusting the average, and send the
    lesson to the agent that can actually repair what failed.
    """
    if grade_report.rubric is None:
        return None
    fatal = grade_report.rubric.fatal_dimensions(fatal_floor)
    if not fatal:
        return None
    detail = ", ".join(f"{dim} {getattr(grade_report.rubric, dim):.0f}" for dim in fatal)
    is_code_defect = any(dim in _CODE_DIMENSIONS for dim in fatal)
    return Classification(
        category=(
            FailureCategory.TEST_FAILURE if is_code_defect else FailureCategory.CONTENT_QUALITY
        ),
        reason=(
            f"Rubric dimension(s) below the fatal floor of {fatal_floor:.0f}: {detail}. "
            f"A composite of {grade_report.quality_score:.0f} cannot make up for it — the "
            + (
                "code does not do what the prose claims."
                if is_code_defect
                else "teaching has a hole the average hides."
            )
        ),
        matched_signals=[f"Fatal rubric dimension(s) below {fatal_floor:.0f}: {detail}"],
    )


def _classify_goal_fit_shape(grade_report: GradeReport) -> Classification | None:
    """Priority 4d: the code does not earn its place → rewrite the lesson's shape.

    `overwhelming` / `insufficient`, checked *below* the rubric so broken code is
    repaired before the lesson is trimmed. Never BLOCKER_STRUCTURE: "there is too
    much machinery here" must not be able to delete the capability the topic asked
    for — the amputation failure doc 11 exists to prevent.
    """
    verdict = grade_report.goal_fit
    if verdict is None or verdict.fit or not verdict.problems:
        return None
    detail = ", ".join(verdict.problems)
    return Classification(
        category=FailureCategory.CONTENT_QUALITY,
        reason=(
            f"The code in this lesson does not earn its place ({detail}): {verdict.text}"
        ),
        matched_signals=[f"Goal-fit verdict: {detail} — {verdict.text[:80]}"],
    )


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
    lesson_mode: LessonMode = "executable",
    fatal_floor: float = FATAL_DIMENSION_FLOOR,
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
                           cells skipped, no worked example) is refused. Callers
                           should compute this with the same lesson_mode.
        fatal_floor: score below which a single rubric dimension refuses the lesson
                     on its own, regardless of the composite. Only consulted when the
                     grade report carries a rubric; a bare score is never gated.
                     See docs/architecture/22-review-that-points-at-the-fix.md → R1.
        lesson_mode: what kind of lesson this is (docs/architecture/17-lesson-modes.md).
                     Defaults to ``"executable"`` — unchanged behavior. In
                     ``"artifact"``/``"conceptual"`` modes, the absence of an
                     execution report (nothing runnable ever ran — e.g. a
                     conceptual lesson has no code at all) is not treated as an
                     execution failure; every other route is unaffected.

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

    # Priorities 4b–4d: judgements about the lesson as a whole rather than about a
    # single finding. Each helper returns a complete Classification or None; the
    # order of the three is the load-bearing part and is explained in the module
    # docstring (drift above the rubric, shape problems below it).
    if grade_report is not None:
        for check in (
            _classify_goal_fit_drift(grade_report),
            _classify_fatal_dimension(grade_report, fatal_floor),
            _classify_goal_fit_shape(grade_report),
        ):
            if check is not None:
                return replace(check, matched_signals=[*signals, *check.matched_signals])

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
    #
    # In non-executable modes, "nothing runnable executed" is not itself a failure:
    # a conceptual lesson legitimately has no code, and an artifact lesson may have
    # few cells. An absent execution_report there must not fall through to the
    # UNCLASSIFIABLE catch-all below just because nothing ran.
    execution_ok = execution_report is not None and execution_report.ok
    execution_not_required = lesson_mode != "executable" and execution_report is None
    if execution_ok or execution_not_required:
        # Anti-hollow backstop: a green, well-graded notebook that nonetheless
        # demonstrates nothing (all cells skipped behind dep guards) must not ship
        # as ACCEPTABLE. This is the deterministic catch for when the LLM student
        # wrongly passes a hollow lesson. Terminate for review rather than loop —
        # replanning cannot conjure the missing runtime. structural_report is
        # already mode-aware (the caller computes it with the same lesson_mode),
        # so this backstop still fires with the mode-appropriate definition.
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
        if execution_ok:
            signals.append("Execution OK and quality acceptable")
            reason = "Code executed successfully and quality is acceptable."
        else:
            signals.append(
                f"No code execution required in '{lesson_mode}' mode; quality acceptable"
            )
            reason = (
                f"No code execution was required for this '{lesson_mode}' lesson, "
                "and quality is acceptable."
            )
        return Classification(
            category=FailureCategory.ACCEPTABLE,
            reason=reason,
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
