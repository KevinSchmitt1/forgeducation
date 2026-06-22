"""Unit tests for failure classification logic.

Tests verify deterministic classification across all 6 FailureCategory values,
edge cases (priority ordering, threshold behaviour), and audit trail correctness.
No LLM calls, no LangGraph dependencies — pure signal-in → category-out.

Run with:
    pytest tests/pipeline/test_failure.py -v
Coverage:
    pytest --cov=forged.pipeline.failure tests/pipeline/test_failure.py
"""

from __future__ import annotations

import pytest

from forged.pipeline.failure import (
    ExecutionReport,
    FailureCategory,
    GradeReport,
    RubricScores,
    classify,
)
from forged.pipeline.state import Evidence, Location, LocationType

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def global_location() -> Location:
    return Location(type=LocationType.GLOBAL)


@pytest.fixture
def cell_location() -> Location:
    return Location(type=LocationType.CELL, cell_index=3)


@pytest.fixture
def structure_location() -> Location:
    return Location(type=LocationType.LESSON_STRUCTURE)


@pytest.fixture
def ok_execution() -> ExecutionReport:
    return ExecutionReport(ok=True)


@pytest.fixture
def failed_execution() -> ExecutionReport:
    return ExecutionReport(ok=False, failed_cells=[2, 5], error_summary="NameError at cell 2")


@pytest.fixture
def high_quality_grade(global_location: Location) -> GradeReport:
    return GradeReport(quality_score=92.0)


@pytest.fixture
def low_quality_grade(global_location: Location) -> GradeReport:
    return GradeReport(quality_score=55.0)


@pytest.fixture
def blocker_structure_evidence(global_location: Location) -> Evidence:
    return Evidence(
        source="student_feedback",
        severity="BLOCKER",
        scope="structure",
        location=global_location,
        text="Collision handling introduced before hash function is defined",
    )


@pytest.fixture
def blocker_plan_evidence(global_location: Location) -> Evidence:
    return Evidence(
        source="student_feedback",
        severity="BLOCKER",
        scope="plan",
        location=global_location,
        text="Prerequisites are in wrong order",
    )


@pytest.fixture
def high_code_evidence(cell_location: Location) -> Evidence:
    return Evidence(
        source="student_feedback",
        severity="HIGH",
        scope="code",
        location=cell_location,
        text="Output does not match expected value",
    )


@pytest.fixture
def blocker_code_evidence(cell_location: Location) -> Evidence:
    return Evidence(
        source="student_feedback",
        severity="BLOCKER",
        scope="code",
        location=cell_location,
        text="Assertion fails: got None, expected dict",
    )


@pytest.fixture
def medium_content_evidence(global_location: Location) -> Evidence:
    return Evidence(
        source="student_feedback",
        severity="MEDIUM",
        scope="content",
        location=global_location,
        text="Explanation of time complexity is unclear",
    )


# ── R1 regression: under-explained-but-correct step must not descope ──────────


@pytest.fixture
def under_explained_executing_cell(cell_location: Location) -> Evidence:
    """The R1 finding: a correct, executing cell that is merely under-explained.

    This is the exact shape that was mis-tagged [BLOCKER/plan] and triggered a
    descoping replan. Correctly scoped, it is `content` — the explanation is thin,
    but the step itself runs and is right.
    """
    return Evidence(
        source="student_feedback",
        severity="BLOCKER",
        scope="content",
        location=cell_location,
        text="Trainer runs but MPS device selection isn't explained",
    )


@pytest.mark.unit
def test_r1_under_explained_executing_step_routes_to_content_not_replan(
    under_explained_executing_cell: Evidence,
    ok_execution: ExecutionReport,
) -> None:
    """R1: a green-executing notebook whose only weakness is content-scoped must
    classify CONTENT_QUALITY (→ content_reviser), never BLOCKER_STRUCTURE (→ planner).

    This guards the lesson-fidelity contract the critic personas must satisfy:
    an under-explained but correct, executing step is `content`, so the loop
    *adds explanation* instead of replanning and amputating the section.
    See docs/architecture/11-topic-fidelity-r1.md → Part V.
    """
    grade = GradeReport(quality_score=77.0, findings=[under_explained_executing_cell])

    result = classify(execution_report=ok_execution, grade_report=grade)

    assert result.category == FailureCategory.CONTENT_QUALITY
    assert result.category != FailureCategory.BLOCKER_STRUCTURE


# ── Category: BLOCKER_STRUCTURE ───────────────────────────────────────────────


@pytest.mark.unit
def test_classify_blocker_structure_when_structure_scope(
    blocker_structure_evidence: Evidence,
) -> None:
    """A BLOCKER finding in the 'structure' scope → BLOCKER_STRUCTURE.

    The lesson plan has a sequencing issue that needs replanning,
    not just code fixes or prose revision.
    """
    grade = GradeReport(quality_score=88.0, findings=[blocker_structure_evidence])

    result = classify(execution_report=None, grade_report=grade)

    assert result.category == FailureCategory.BLOCKER_STRUCTURE


@pytest.mark.unit
def test_classify_blocker_structure_when_plan_scope(
    blocker_plan_evidence: Evidence,
) -> None:
    """A BLOCKER finding in the 'plan' scope → BLOCKER_STRUCTURE."""
    grade = GradeReport(quality_score=88.0, findings=[blocker_plan_evidence])

    result = classify(execution_report=None, grade_report=grade)

    assert result.category == FailureCategory.BLOCKER_STRUCTURE


@pytest.mark.unit
def test_classify_blocker_structure_reason_is_informative(
    blocker_structure_evidence: Evidence,
) -> None:
    """Classification reason must describe the problem for humans reading the audit trail."""
    grade = GradeReport(quality_score=88.0, findings=[blocker_structure_evidence])

    result = classify(execution_report=None, grade_report=grade)

    assert len(result.reason) > 10  # non-trivial explanation
    assert result.reason  # not empty


@pytest.mark.unit
def test_classify_blocker_structure_matched_signals_include_finding_text(
    blocker_structure_evidence: Evidence,
) -> None:
    """matched_signals must include enough context to trace back to the evidence."""
    grade = GradeReport(quality_score=88.0, findings=[blocker_structure_evidence])

    result = classify(execution_report=None, grade_report=grade)

    assert len(result.matched_signals) >= 1
    combined = " ".join(result.matched_signals)
    assert "BLOCKER" in combined


# ── Category: CODE_QUALITY ────────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_code_quality_when_execution_fails(
    failed_execution: ExecutionReport,
) -> None:
    """Failed execution → CODE_QUALITY regardless of grade report.

    The notebook crashed; there is nothing meaningful to grade yet.
    Routing back to CodeAuthor is the correct response.
    """
    result = classify(execution_report=failed_execution, grade_report=None)

    assert result.category == FailureCategory.CODE_QUALITY


@pytest.mark.unit
def test_classify_code_quality_with_failed_cells_in_reason(
    failed_execution: ExecutionReport,
) -> None:
    """Reason must surface failed cell numbers so the CodeAuthor knows where to look."""
    result = classify(execution_report=failed_execution, grade_report=None)

    assert "2" in result.reason or "2" in " ".join(result.matched_signals)


@pytest.mark.unit
def test_classify_code_quality_when_execution_fails_ignores_grade(
    failed_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """Even a perfect grade report must not mask a failed execution.

    Execution failure takes priority over quality score (priority cascade).
    """
    result = classify(execution_report=failed_execution, grade_report=high_quality_grade)

    assert result.category == FailureCategory.CODE_QUALITY


@pytest.mark.unit
def test_classify_code_quality_matched_signals_include_cell_list(
    failed_execution: ExecutionReport,
) -> None:
    """The matched_signals list must reveal which cells failed for auditability."""
    result = classify(execution_report=failed_execution, grade_report=None)

    combined = " ".join(result.matched_signals)
    assert "Execution" in combined or "[2" in combined or "2" in combined


# ── Category: TEST_FAILURE ────────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_test_failure_when_code_runs_high_severity_code_finding(
    ok_execution: ExecutionReport,
    high_code_evidence: Evidence,
) -> None:
    """Code runs but HIGH-severity code finding → TEST_FAILURE.

    The notebook executes without error but produces wrong outputs,
    which is a different failure mode from the code not running at all.
    """
    grade = GradeReport(quality_score=60.0, findings=[high_code_evidence])

    result = classify(execution_report=ok_execution, grade_report=grade)

    assert result.category == FailureCategory.TEST_FAILURE


@pytest.mark.unit
def test_classify_test_failure_when_code_runs_blocker_code_finding(
    ok_execution: ExecutionReport,
    blocker_code_evidence: Evidence,
) -> None:
    """A BLOCKER-severity code finding on a running notebook → TEST_FAILURE."""
    grade = GradeReport(quality_score=50.0, findings=[blocker_code_evidence])

    result = classify(execution_report=ok_execution, grade_report=grade)

    assert result.category == FailureCategory.TEST_FAILURE


@pytest.mark.unit
def test_classify_test_failure_requires_code_scope(
    ok_execution: ExecutionReport,
    medium_content_evidence: Evidence,
) -> None:
    """MEDIUM content finding with ok execution must not produce TEST_FAILURE.

    Only HIGH/BLOCKER findings scoped to 'code' trigger this category.
    """
    grade = GradeReport(quality_score=90.0, findings=[medium_content_evidence])

    result = classify(execution_report=ok_execution, grade_report=grade)

    assert result.category != FailureCategory.TEST_FAILURE


@pytest.mark.unit
def test_classify_test_failure_matched_signals_mention_finding(
    ok_execution: ExecutionReport,
    high_code_evidence: Evidence,
) -> None:
    """matched_signals must reference the code finding so it can be traced."""
    grade = GradeReport(quality_score=60.0, findings=[high_code_evidence])

    result = classify(execution_report=ok_execution, grade_report=grade)

    combined = " ".join(result.matched_signals)
    assert "code" in combined.lower() or "HIGH" in combined or "finding" in combined.lower()


# ── Category: CONTENT_QUALITY ─────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_content_quality_when_score_below_threshold(
    ok_execution: ExecutionReport,
    low_quality_grade: GradeReport,
) -> None:
    """Low quality score with ok execution → CONTENT_QUALITY.

    The code runs but the teaching is unclear; prose revision is needed.
    """
    result = classify(execution_report=ok_execution, grade_report=low_quality_grade)

    assert result.category == FailureCategory.CONTENT_QUALITY


@pytest.mark.unit
def test_classify_content_quality_reason_includes_scores(
    ok_execution: ExecutionReport,
    low_quality_grade: GradeReport,
) -> None:
    """Reason must state both actual score and threshold for human readability."""
    result = classify(execution_report=ok_execution, grade_report=low_quality_grade)

    assert "55" in result.reason or "55" in " ".join(result.matched_signals)


@pytest.mark.unit
def test_classify_content_quality_matched_signals_include_score(
    ok_execution: ExecutionReport,
    low_quality_grade: GradeReport,
) -> None:
    """matched_signals must state the numeric score so audit readers know the threshold."""
    result = classify(execution_report=ok_execution, grade_report=low_quality_grade)

    combined = " ".join(result.matched_signals)
    assert "55" in combined or "quality" in combined.lower()


# ── Category: ACCEPTABLE ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_acceptable_when_execution_ok_and_quality_meets_threshold(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """Execution ok + quality >= threshold → ACCEPTABLE.

    Pipeline should terminate; no further routing needed.
    """
    result = classify(execution_report=ok_execution, grade_report=high_quality_grade)

    assert result.category == FailureCategory.ACCEPTABLE


@pytest.mark.unit
def test_classify_acceptable_when_execution_ok_and_no_grade_report(
    ok_execution: ExecutionReport,
) -> None:
    """Execution ok with no grade report is acceptable (grader hasn't run yet, but code works).

    quality score is not required when there is no grade report.
    """
    result = classify(execution_report=ok_execution, grade_report=None)

    assert result.category == FailureCategory.ACCEPTABLE


@pytest.mark.unit
def test_classify_acceptable_matched_signals_confirm_ok_state(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """matched_signals must confirm what passed, not just that it did."""
    result = classify(execution_report=ok_execution, grade_report=high_quality_grade)

    combined = " ".join(result.matched_signals).lower()
    assert "ok" in combined or "acceptable" in combined or "quality" in combined


# ── Category: UNCLASSIFIABLE ──────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_unclassifiable_when_both_reports_none() -> None:
    """No execution or grade report → UNCLASSIFIABLE.

    The classifier cannot make a determination without any signals.
    This surfaces for human review rather than silently continuing.
    """
    result = classify(execution_report=None, grade_report=None)

    assert result.category == FailureCategory.UNCLASSIFIABLE


@pytest.mark.unit
def test_classify_unclassifiable_reason_recommends_manual_review() -> None:
    """Reason must guide the human reviewer on what action to take."""
    result = classify(execution_report=None, grade_report=None)

    assert len(result.reason) > 5  # non-trivial
    assert result.reason  # not empty


@pytest.mark.unit
def test_classify_unclassifiable_matched_signals_not_empty() -> None:
    """Even UNCLASSIFIABLE must produce at least one matched_signal for audit trail."""
    result = classify(execution_report=None, grade_report=None)

    assert len(result.matched_signals) >= 1


# ── Priority cascade edge cases ───────────────────────────────────────────────


@pytest.mark.unit
def test_classify_blocker_structure_takes_priority_over_execution_failure(
    failed_execution: ExecutionReport,
    blocker_structure_evidence: Evidence,
) -> None:
    """BLOCKER_STRUCTURE is checked first (priority 1), before CODE_QUALITY (priority 2).

    When both signals exist, replanning is more important than recoding
    because a structurally broken plan would produce broken code again.
    """
    grade = GradeReport(quality_score=30.0, findings=[blocker_structure_evidence])

    result = classify(execution_report=failed_execution, grade_report=grade)

    assert result.category == FailureCategory.BLOCKER_STRUCTURE


@pytest.mark.unit
def test_classify_execution_failure_takes_priority_over_content_quality(
    failed_execution: ExecutionReport,
    low_quality_grade: GradeReport,
) -> None:
    """CODE_QUALITY (priority 2) precedes CONTENT_QUALITY (priority 4).

    A notebook that does not run is a harder problem than poor prose.
    """
    result = classify(execution_report=failed_execution, grade_report=low_quality_grade)

    assert result.category == FailureCategory.CODE_QUALITY


@pytest.mark.unit
def test_classify_test_failure_takes_priority_over_content_quality(
    ok_execution: ExecutionReport,
    high_code_evidence: Evidence,
) -> None:
    """TEST_FAILURE (priority 3) precedes CONTENT_QUALITY (priority 4).

    Wrong outputs need a code fix, not a prose revision.
    """
    grade = GradeReport(quality_score=50.0, findings=[high_code_evidence])

    result = classify(execution_report=ok_execution, grade_report=grade)

    assert result.category == FailureCategory.TEST_FAILURE


@pytest.mark.unit
def test_classify_first_blocker_finding_wins_among_multiple_findings(
    global_location: Location,
    cell_location: Location,
) -> None:
    """When multiple BLOCKER findings exist, the first one in the list drives the decision.

    Ordering is stable across all invocations; no randomness.
    """
    finding1 = Evidence(
        source="student_feedback",
        severity="BLOCKER",
        scope="structure",
        location=global_location,
        text="First blocker: concept ordering wrong",
    )
    finding2 = Evidence(
        source="student_feedback",
        severity="BLOCKER",
        scope="structure",
        location=cell_location,
        text="Second blocker: prerequisites missing",
    )
    grade = GradeReport(quality_score=70.0, findings=[finding1, finding2])

    result = classify(execution_report=None, grade_report=grade)

    assert result.category == FailureCategory.BLOCKER_STRUCTURE
    # First blocker's text must appear in the matched signals
    combined = " ".join(result.matched_signals)
    assert "First blocker" in combined or "concept ordering" in combined


# ── Quality threshold parameterisation ────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "score, threshold, expected_category",
    [
        (59.9, 60.0, FailureCategory.CONTENT_QUALITY),   # just below threshold
        (60.0, 60.0, FailureCategory.ACCEPTABLE),         # exactly at threshold → acceptable
        (79.9, 80.0, FailureCategory.CONTENT_QUALITY),   # below default threshold
        (80.0, 80.0, FailureCategory.ACCEPTABLE),         # at default threshold → acceptable
        (100.0, 80.0, FailureCategory.ACCEPTABLE),        # perfect score
        (0.0, 80.0, FailureCategory.CONTENT_QUALITY),    # zero score
    ],
)
def test_classify_respects_quality_threshold(
    score: float,
    threshold: float,
    expected_category: FailureCategory,
) -> None:
    """Boundary behaviour: score == threshold is ACCEPTABLE; below is CONTENT_QUALITY.

    The classifier must treat the threshold as a >=  comparison.
    """
    grade = GradeReport(quality_score=score)
    exec_report = ExecutionReport(ok=True)

    result = classify(
        execution_report=exec_report,
        grade_report=grade,
        quality_threshold=threshold,
    )

    assert result.category == expected_category


# ── Determinism ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_classify_is_deterministic_for_blocker_structure(
    blocker_structure_evidence: Evidence,
) -> None:
    """Same inputs must produce the same output on every invocation.

    No RNG, no LLM calls. This is a fundamental correctness guarantee.
    """
    grade = GradeReport(quality_score=70.0, findings=[blocker_structure_evidence])
    exec_report = ExecutionReport(ok=False, failed_cells=[1])

    results = [
        classify(execution_report=exec_report, grade_report=grade)
        for _ in range(10)
    ]

    categories = {r.category for r in results}
    reasons = {r.reason for r in results}

    assert len(categories) == 1, f"Non-deterministic categories: {categories}"
    assert len(reasons) == 1, f"Non-deterministic reasons: {reasons}"


@pytest.mark.unit
def test_classify_is_deterministic_for_code_quality(
    failed_execution: ExecutionReport,
) -> None:
    """CODE_QUALITY classification must be identical across 10 runs."""
    results = [
        classify(execution_report=failed_execution, grade_report=None)
        for _ in range(10)
    ]

    categories = {r.category for r in results}
    assert len(categories) == 1


@pytest.mark.unit
def test_classify_is_deterministic_for_acceptable(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """ACCEPTABLE classification must be identical across 10 runs."""
    results = [
        classify(execution_report=ok_execution, grade_report=high_quality_grade)
        for _ in range(10)
    ]

    categories = {r.category for r in results}
    assert len(categories) == 1


@pytest.mark.unit
def test_classify_is_deterministic_for_unclassifiable() -> None:
    """UNCLASSIFIABLE must be stable — no random fallback logic."""
    results = [
        classify(execution_report=None, grade_report=None)
        for _ in range(10)
    ]

    categories = {r.category for r in results}
    assert len(categories) == 1


# ── matched_signals auditability ──────────────────────────────────────────────


@pytest.mark.unit
def test_matched_signals_is_list_of_strings(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """matched_signals must be a list of strings; never None or empty for auditing."""
    result = classify(execution_report=ok_execution, grade_report=high_quality_grade)

    assert isinstance(result.matched_signals, list)
    assert all(isinstance(s, str) for s in result.matched_signals)


@pytest.mark.unit
def test_matched_signals_always_non_empty_for_all_categories(
    ok_execution: ExecutionReport,
    failed_execution: ExecutionReport,
    high_quality_grade: GradeReport,
    low_quality_grade: GradeReport,
    blocker_structure_evidence: Evidence,
    high_code_evidence: Evidence,
) -> None:
    """Every category must produce at least one matched_signal.

    Ensures audit trail is never empty regardless of classification path.
    """
    cases = [
        # (execution_report, grade_report)
        (None, GradeReport(quality_score=88.0, findings=[blocker_structure_evidence])),
        (failed_execution, None),
        (ok_execution, GradeReport(quality_score=60.0, findings=[high_code_evidence])),
        (ok_execution, low_quality_grade),
        (ok_execution, high_quality_grade),
        (None, None),
    ]

    for exec_report, grade_report in cases:
        result = classify(execution_report=exec_report, grade_report=grade_report)
        assert len(result.matched_signals) >= 1, (
            f"Empty matched_signals for category {result.category}"
        )


@pytest.mark.unit
def test_matched_signals_contain_reason_text_for_code_quality(
    failed_execution: ExecutionReport,
) -> None:
    """matched_signals for CODE_QUALITY must contain enough context to understand the failure."""
    result = classify(execution_report=failed_execution, grade_report=None)

    # At least one signal should mention execution or the failed cells
    combined = " ".join(result.matched_signals).lower()
    assert "execut" in combined or "fail" in combined or "cell" in combined


# ── Classification is a frozen dataclass ──────────────────────────────────────


@pytest.mark.unit
def test_classification_is_immutable(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """Classification must be a frozen dataclass — immutability is non-negotiable."""
    result = classify(execution_report=ok_execution, grade_report=high_quality_grade)

    with pytest.raises((TypeError, AttributeError)):
        result.category = FailureCategory.UNCLASSIFIABLE  # type: ignore[misc]


@pytest.mark.unit
def test_execution_report_is_immutable(ok_execution: ExecutionReport) -> None:
    """ExecutionReport must be frozen to prevent mutation after creation."""
    with pytest.raises((TypeError, AttributeError)):
        ok_execution.ok = False  # type: ignore[misc]


@pytest.mark.unit
def test_grade_report_is_immutable(high_quality_grade: GradeReport) -> None:
    """GradeReport must be frozen to prevent mutation after creation."""
    with pytest.raises((TypeError, AttributeError)):
        high_quality_grade.quality_score = 0.0  # type: ignore[misc]


# ── ExecutionReport defaults ──────────────────────────────────────────────────


@pytest.mark.unit
def test_execution_report_defaults_failed_cells_to_empty_list() -> None:
    """failed_cells defaults to an empty list when not provided."""
    report = ExecutionReport(ok=True)
    assert report.failed_cells == []


@pytest.mark.unit
def test_execution_report_defaults_error_summary_to_none() -> None:
    """error_summary defaults to None when not provided."""
    report = ExecutionReport(ok=False)
    assert report.error_summary is None


# ── GradeReport defaults ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_grade_report_defaults_blockers_to_empty_list() -> None:
    """blockers defaults to an empty list when not provided."""
    report = GradeReport(quality_score=80.0)
    assert report.blockers == []


@pytest.mark.unit
def test_grade_report_defaults_findings_to_empty_list() -> None:
    """findings defaults to an empty list when not provided."""
    report = GradeReport(quality_score=80.0)
    assert report.findings == []


# ── All 6 FailureCategory values exist ────────────────────────────────────────


@pytest.mark.unit
def test_failure_category_has_all_six_values() -> None:
    """Enum must define exactly the 6 documented categories — no more, no fewer."""
    expected = {
        "BLOCKER_STRUCTURE",
        "CODE_QUALITY",
        "TEST_FAILURE",
        "CONTENT_QUALITY",
        "ACCEPTABLE",
        "UNCLASSIFIABLE",
    }
    actual = {member.name for member in FailureCategory}

    assert actual == expected


@pytest.mark.unit
def test_failure_category_values_are_lowercase_strings() -> None:
    """FailureCategory inherits from str; values must be lowercase for downstream routing."""
    for member in FailureCategory:
        assert member.value == member.value.lower()
        assert isinstance(member.value, str)


# ── RubricScores ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rubric_composite_is_mean_of_dimensions() -> None:
    """composite() is the equal-weighted mean of the five dimensions."""
    rubric = RubricScores(
        structure=80.0,
        explanation_depth=60.0,
        code_clarity=70.0,
        correctness=90.0,
        learner_fit=50.0,
    )
    assert rubric.composite() == pytest.approx((80 + 60 + 70 + 90 + 50) / 5)


@pytest.mark.unit
def test_rubric_is_immutable() -> None:
    """RubricScores must be frozen — it is part of the audit trail."""
    rubric = RubricScores(
        structure=1.0, explanation_depth=1.0, code_clarity=1.0,
        correctness=1.0, learner_fit=1.0,
    )
    with pytest.raises((TypeError, AttributeError)):
        rubric.structure = 99.0  # type: ignore[misc]


@pytest.mark.unit
def test_grade_report_rubric_defaults_to_none() -> None:
    """rubric is optional; legacy GradeReport(quality_score=...) still works."""
    assert GradeReport(quality_score=80.0).rubric is None


@pytest.mark.unit
def test_grade_report_graded_defaults_to_true() -> None:
    """A grade report is graded unless explicitly marked as a failed assessment."""
    assert GradeReport(quality_score=80.0).graded is True


# ── Failed grade → UNCLASSIFIABLE (not low content) ───────────────────────────


@pytest.mark.unit
def test_classify_failed_grade_is_unclassifiable_not_content_quality(
    ok_execution: ExecutionReport,
) -> None:
    """A failed grade (graded=False) must NOT be treated as poor content.

    This is the regression guard for the localLLM run: a student LLM failure fell
    back to score 50 and was routed to the no-op reviser. An ungraded report is an
    absence of signal → UNCLASSIFIABLE (human review), never CONTENT_QUALITY.
    """
    ungraded = GradeReport(quality_score=50.0, graded=False)

    result = classify(execution_report=ok_execution, grade_report=ungraded)

    assert result.category == FailureCategory.UNCLASSIFIABLE
    assert result.category != FailureCategory.CONTENT_QUALITY


@pytest.mark.unit
def test_classify_execution_failure_beats_failed_grade(
    failed_execution: ExecutionReport,
) -> None:
    """A real execution failure still wins over an ungraded report.

    If the code didn't run, that concrete signal routes to CodeAuthor regardless
    of whether grading succeeded.
    """
    ungraded = GradeReport(quality_score=50.0, graded=False)

    result = classify(execution_report=failed_execution, grade_report=ungraded)

    assert result.category == FailureCategory.CODE_QUALITY


@pytest.mark.unit
def test_classify_none_grade_with_ok_execution_still_acceptable(
    ok_execution: ExecutionReport,
) -> None:
    """grade_report=None (grader not run) stays ACCEPTABLE — distinct from graded=False.

    Pins the boundary: 'no grader yet' is not the same as 'grader failed'.
    """
    result = classify(execution_report=ok_execution, grade_report=None)

    assert result.category == FailureCategory.ACCEPTABLE


# ── Structural (anti-hollow) gate ─────────────────────────────────────────────


@pytest.mark.unit
def test_classify_hollow_notebook_is_not_acceptable(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """A green, well-graded but hollow notebook → UNCLASSIFIABLE, never ACCEPTABLE.

    This is the deterministic backstop for when the LLM student wrongly passes a
    lesson whose core cells were all skipped.
    """
    from forged.pipeline.structure import StructuralReport

    hollow = StructuralReport(is_hollow=True, reasons=["4 of 6 code cells were skipped"])

    result = classify(
        execution_report=ok_execution,
        grade_report=high_quality_grade,
        structural_report=hollow,
    )

    assert result.category == FailureCategory.UNCLASSIFIABLE
    assert "skipped" in result.reason


@pytest.mark.unit
def test_classify_non_hollow_structure_still_acceptable(
    ok_execution: ExecutionReport,
    high_quality_grade: GradeReport,
) -> None:
    """A healthy structural report does not disturb the ACCEPTABLE verdict."""
    from forged.pipeline.structure import StructuralReport

    healthy = StructuralReport(is_hollow=False)

    result = classify(
        execution_report=ok_execution,
        grade_report=high_quality_grade,
        structural_report=healthy,
    )

    assert result.category == FailureCategory.ACCEPTABLE


@pytest.mark.unit
def test_classify_structural_gate_does_not_override_low_quality(
    ok_execution: ExecutionReport,
    low_quality_grade: GradeReport,
) -> None:
    """A low grade still routes to CONTENT_QUALITY before the structural gate is reached.

    The gate only guards the ACCEPTABLE path; it must not pre-empt the normal
    content-revision route.
    """
    from forged.pipeline.structure import StructuralReport

    hollow = StructuralReport(is_hollow=True, reasons=["hollow"])

    result = classify(
        execution_report=ok_execution,
        grade_report=low_quality_grade,
        structural_report=hollow,
    )

    assert result.category == FailureCategory.CONTENT_QUALITY
