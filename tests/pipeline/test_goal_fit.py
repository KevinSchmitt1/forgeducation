"""The goal-fit verdict: does the code in this lesson earn its place? (doc 22, D6/R5)

The rubric's five dimensions all ask *how well the code that exists is presented*. None
asks whether it should exist — which is precisely the founding complaint of this project
(doc 18: lessons come out code-heavy and not practical), so nothing in the review could
catch it.

R5 adds that judgement as a **separate verdict beside the rubric**, not a sixth
dimension. Kevin's call, 2026-08-16, for the reason D1 exists: averaging is what hid the
fatal condition in the first place, so the fix must not be more arithmetic. A sixth
dimension would also make every historical composite incomparable.

The two critics answer it from their own side (doc 22, open question 2):
  * Student  — "was this too much, or too little, for *me* to reach the goal?"
               vocabulary: overwhelming / insufficient
  * Reviewer — "was this the right material at all?"
               vocabulary: drifted / overwhelming / insufficient

Only the Reviewer can say `drifted`, and that asymmetry is load-bearing: `drifted` is the
one problem that routes to the planner, and letting a simulated novice's "this feels
off-topic" trigger a replan is the amputation failure doc 11 exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forged.pipeline.failure import (
    ExecutionReport,
    FailureCategory,
    GoalFitVerdict,
    GradeReport,
    RubricScores,
    classify,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ok_execution() -> ExecutionReport:
    return ExecutionReport(ok=True)


@pytest.fixture
def healthy_rubric() -> RubricScores:
    """A rubric with nothing wrong in it — so only the goal-fit verdict can refuse."""
    return RubricScores(
        structure=90.0,
        explanation_depth=90.0,
        code_clarity=90.0,
        correctness=90.0,
        learner_fit=90.0,
    )


@pytest.fixture
def broken_rubric() -> RubricScores:
    """v0's real rubric: correctness 40, fatal on its own (doc 22 R1)."""
    return RubricScores(
        structure=90.0,
        explanation_depth=85.0,
        code_clarity=70.0,
        correctness=40.0,
        learner_fit=85.0,
    )


def _graded(rubric: RubricScores, goal_fit: GoalFitVerdict | None) -> GradeReport:
    return GradeReport(
        quality_score=rubric.composite(), rubric=rubric, goal_fit=goal_fit
    )


# ── The verdict value object ──────────────────────────────────────────────────


@pytest.mark.unit
def test_a_fitting_verdict_carries_no_problems() -> None:
    verdict = GoalFitVerdict(fit=True, text="Every cell serves the stated objective.")

    assert verdict.fit is True
    assert verdict.problems == ()


@pytest.mark.unit
def test_a_lesson_can_be_overwhelming_and_insufficient_at_once() -> None:
    """Doc 22's requirement: one axis, two failure directions, both reportable.

    "A grader forced to pick a direction will say 'fine'" — the 2026-08-13 run was
    both at once, so `problems` is a set of flags, never a single choice.
    """
    verdict = GoalFitVerdict(
        fit=False,
        problems=("overwhelming", "insufficient"),
        text="26 cells of scaffolding, and still no worked example of the actual idea.",
    )

    assert set(verdict.problems) == {"overwhelming", "insufficient"}


@pytest.mark.unit
def test_merging_two_verdicts_takes_the_union_of_problems() -> None:
    """The reviser merges both critics before classifying, as it does for findings."""
    student = GoalFitVerdict(fit=False, problems=("overwhelming",), text="Too much.")
    reviewer = GoalFitVerdict(fit=False, problems=("drifted",), text="Wrong subject.")

    merged = student.merged_with(reviewer)

    assert merged.fit is False
    assert merged.problems == ("drifted", "overwhelming")  # canonical order
    assert "Too much." in merged.text and "Wrong subject." in merged.text


@pytest.mark.unit
def test_one_critic_refusing_is_enough_to_refuse() -> None:
    """Fit requires both critics to agree; either one may withhold it."""
    fitting = GoalFitVerdict(fit=True, text="Fine by me.")
    refusing = GoalFitVerdict(fit=False, problems=("insufficient",), text="Too thin.")

    assert fitting.merged_with(refusing).fit is False
    assert refusing.merged_with(fitting).fit is False


@pytest.mark.unit
def test_merging_with_nothing_returns_the_verdict_unchanged() -> None:
    """Only one critic produced a verdict (the other degraded) — carry it alone."""
    verdict = GoalFitVerdict(fit=False, problems=("drifted",), text="Wrong subject.")

    assert verdict.merged_with(None) == verdict


@pytest.mark.unit
def test_a_verdict_is_immutable() -> None:
    verdict = GoalFitVerdict(fit=True)

    with pytest.raises((TypeError, AttributeError)):
        verdict.fit = False  # type: ignore[misc]


# ── Routing: drift is the one that reaches the planner ────────────────────────


@pytest.mark.unit
def test_drift_replans_even_when_every_other_signal_is_healthy(
    ok_execution: ExecutionReport, healthy_rubric: RubricScores
) -> None:
    """A green notebook that teaches the wrong subject must not ship.

    Doc 22 Part III sanctions a remake for exactly this shape: "the plan was
    misread, the lesson teaches the wrong subject".
    """
    verdict = GoalFitVerdict(
        fit=False,
        problems=("drifted",),
        text="The objective was a Copilot config; the lesson teaches argparse.",
    )

    result = classify(ok_execution, _graded(healthy_rubric, verdict))

    assert result.category == FailureCategory.BLOCKER_STRUCTURE


@pytest.mark.unit
def test_drift_outranks_a_fatal_rubric_dimension(
    ok_execution: ExecutionReport, broken_rubric: RubricScores
) -> None:
    """Fixing code in a lesson about the wrong subject throws the fix away.

    So drift is checked *above* R1's fatal-dimension gate: replan first.
    """
    verdict = GoalFitVerdict(fit=False, problems=("drifted",), text="Wrong subject.")

    result = classify(ok_execution, _graded(broken_rubric, verdict))

    assert result.category == FailureCategory.BLOCKER_STRUCTURE


@pytest.mark.unit
def test_execution_failure_still_outranks_drift(
    healthy_rubric: RubricScores,
) -> None:
    """Priority 2 is unmoved: a notebook that did not run is CODE_QUALITY."""
    verdict = GoalFitVerdict(fit=False, problems=("drifted",), text="Wrong subject.")
    failed = ExecutionReport(ok=False, failed_cells=[3], error_summary="SyntaxError")

    result = classify(failed, _graded(healthy_rubric, verdict))

    assert result.category == FailureCategory.CODE_QUALITY


# ── Routing: shape problems go to the reviser, never the planner ──────────────


@pytest.mark.unit
@pytest.mark.parametrize("problem", ["overwhelming", "insufficient"])
def test_a_shape_problem_refuses_acceptable_and_routes_to_content(
    problem: str, ok_execution: ExecutionReport, healthy_rubric: RubricScores
) -> None:
    """90s across the rubric, and the lesson still does not earn its place.

    Never BLOCKER_STRUCTURE: "there is too much machinery here" must not be able to
    delete the capability the topic asked for (doc 11).
    """
    verdict = GoalFitVerdict(fit=False, problems=(problem,), text="Does not earn it.")

    result = classify(ok_execution, _graded(healthy_rubric, verdict))

    assert result.category == FailureCategory.CONTENT_QUALITY


@pytest.mark.unit
def test_a_fatal_dimension_outranks_a_shape_problem(
    ok_execution: ExecutionReport, broken_rubric: RubricScores
) -> None:
    """Broken code is fixed before the lesson is trimmed.

    The reverse order would hand a wrong-code lesson to the reviser to shorten.
    """
    verdict = GoalFitVerdict(fit=False, problems=("overwhelming",), text="Too much.")

    result = classify(ok_execution, _graded(broken_rubric, verdict))

    assert result.category == FailureCategory.TEST_FAILURE


# ── The gate is inert unless a critic actually refused ────────────────────────


@pytest.mark.unit
def test_a_fitting_verdict_still_ships(
    ok_execution: ExecutionReport, healthy_rubric: RubricScores
) -> None:
    verdict = GoalFitVerdict(fit=True, text="Every cell serves the objective.")

    result = classify(ok_execution, _graded(healthy_rubric, verdict))

    assert result.category == FailureCategory.ACCEPTABLE


@pytest.mark.unit
def test_no_verdict_leaves_classification_unchanged(
    ok_execution: ExecutionReport, healthy_rubric: RubricScores
) -> None:
    """A provider that returns no verdict (Ollama, a degraded grader) is not gated.

    The absence of a judgement is not a negative judgement — the same rule the
    grade report already follows for a missing rubric.
    """
    with_verdict = classify(ok_execution, _graded(healthy_rubric, None))

    assert with_verdict.category == FailureCategory.ACCEPTABLE


@pytest.mark.unit
def test_the_reason_names_the_problems_and_quotes_the_critic(
    ok_execution: ExecutionReport, healthy_rubric: RubricScores
) -> None:
    """Auditability: this reason is what reaches the revision brief.

    "The lesson does not earn its place" is not actionable; naming which way, and
    in the critic's own words, is.
    """
    verdict = GoalFitVerdict(
        fit=False,
        problems=("overwhelming", "insufficient"),
        text="Six helper classes, and the idea itself is never demonstrated.",
    )

    result = classify(ok_execution, _graded(healthy_rubric, verdict))

    combined = result.reason + " " + " ".join(result.matched_signals)
    assert "overwhelming" in combined
    assert "insufficient" in combined
    assert "Six helper classes" in combined


# ── The reviser reads it, merges it, and puts it in the brief ─────────────────


def _agent(tmp_path: Path):
    from forged.pipeline.agents.reviser import RevisorAgent

    personas = tmp_path / "personas"
    personas.mkdir(exist_ok=True)
    (personas / "reviser.md").write_text("You are the Reviser.", encoding="utf-8")
    return RevisorAgent(personas_dir=personas)


@pytest.mark.unit
def test_the_verdict_is_parsed_from_grade_report_json(tmp_path: Path) -> None:
    """The student's JSON carries the verdict through to the classifier."""
    agent = _agent(tmp_path)

    verdict = agent._coerce_goal_fit(
        {"fit": False, "problems": ["overwhelming"], "text": "Too much machinery."}
    )

    assert verdict is not None
    assert verdict.fit is False
    assert verdict.problems == ("overwhelming",)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not a dict",
        {"problems": ["overwhelming"]},          # no fit flag
        {"fit": "yes", "problems": []},          # fit is not a bool
    ],
)
def test_a_malformed_verdict_degrades_to_none(raw: object, tmp_path: Path) -> None:
    """Same read-and-degrade rule as the rubric: drop it, never crash the loop."""
    assert _agent(tmp_path)._coerce_goal_fit(raw) is None


@pytest.mark.unit
def test_unknown_problem_labels_are_dropped_not_trusted(tmp_path: Path) -> None:
    """A model inventing a fourth label must not smuggle in a routing decision.

    Only the canonical vocabulary routes; `drifted` in particular reaches the
    planner, so an unrecognised string can never be treated as one.
    """
    verdict = _agent(tmp_path)._coerce_goal_fit(
        {"fit": False, "problems": ["drifted", "vibes"], "text": "x"}
    )

    assert verdict is not None
    assert verdict.problems == ("drifted",)


@pytest.mark.unit
def test_the_student_verdict_is_not_allowed_to_claim_drift(tmp_path: Path) -> None:
    """Only the expert reviewer can send a lesson back to the planner.

    The student is a simulated novice; a novice's "this feels off-topic" triggering
    a replan is the amputation failure doc 11 exists to prevent. Enforced here, not
    only in the persona, because personas are advisory and this is load-bearing.
    """
    verdict = _agent(tmp_path)._coerce_goal_fit(
        {"fit": False, "problems": ["drifted", "overwhelming"], "text": "x"},
        allow_drift=False,
    )

    assert verdict is not None
    assert verdict.problems == ("overwhelming",)


@pytest.mark.unit
def test_the_brief_carries_the_verdict_to_the_next_agent(tmp_path: Path) -> None:
    """A judgement the next agent never sees changes nothing."""
    from forged.pipeline.failure import Classification
    from forged.pipeline.state import PipelineStage

    agent = _agent(tmp_path)
    rubric = RubricScores(
        structure=90.0,
        explanation_depth=90.0,
        code_clarity=90.0,
        correctness=90.0,
        learner_fit=90.0,
    )
    grade = GradeReport(
        quality_score=90.0,
        rubric=rubric,
        goal_fit=GoalFitVerdict(
            fit=False,
            problems=("overwhelming",),
            text="Six helper classes the learner never touches again.",
        ),
    )

    brief = agent._synthesize_revision_brief(
        ExecutionReport(ok=True),
        grade,
        Classification(
            category=FailureCategory.CONTENT_QUALITY, reason="Does not earn its place."
        ),
        PipelineStage.CONTENT_REVISER,
    )

    assert "overwhelming" in brief
    assert "Six helper classes" in brief


@pytest.mark.unit
def test_the_brief_is_unchanged_when_no_verdict_was_produced(tmp_path: Path) -> None:
    """No verdict must not alter a brief that previously had none."""
    from forged.pipeline.failure import Classification
    from forged.pipeline.state import PipelineStage

    agent = _agent(tmp_path)
    args = (
        ExecutionReport(ok=True),
        GradeReport(quality_score=90.0, rubric=None),
        Classification(category=FailureCategory.CONTENT_QUALITY, reason="Thin prose."),
        PipelineStage.CONTENT_REVISER,
    )
    brief = agent._synthesize_revision_brief(*args)

    assert "Goal fit" not in brief
    assert "goal-fit" not in brief


@pytest.mark.unit
def test_both_critics_verdicts_are_merged_before_classifying(tmp_path: Path) -> None:
    """End-to-end through the reviser's real reader: student + reviewer JSON in.

    The student says "too much for me"; only the reviewer can say the material was
    wrong. Merged, the drift wins the route.
    """
    from forged.artifacts import Artifact, ArtifactStore
    from forged.pipeline.state import PipelineStage, PipelineState

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    store = ArtifactStore(run_dir=run_dir)
    store.put(
        Artifact(
            name="student_grade_report_v0",
            kind="json",
            content=json.dumps(
                {
                    "quality_score": 90.0,
                    "rubric": None,
                    "graded": True,
                    "blockers": [],
                    "findings": [],
                    "goal_fit": {
                        "fit": False,
                        "problems": ["overwhelming"],
                        "text": "Too much for me.",
                    },
                }
            ),
        )
    )
    store.put(
        Artifact(
            name="reviewer_report_v0",
            kind="json",
            content=json.dumps(
                {
                    "verdict": "Wrong material.",
                    "blockers": [],
                    "findings": [],
                    "goal_fit": {
                        "fit": False,
                        "problems": ["drifted"],
                        "text": "Teaches argparse, not the stated objective.",
                    },
                }
            ),
        )
    )

    agent = _agent(tmp_path)
    state = PipelineState(
        run_id="r", current_stage=PipelineStage.REVISER, iteration=0
    )
    grade = agent._read_grade_report(state, store)
    merged = agent._merge_reviewer_findings(state, store, grade)

    assert merged is not None and merged.goal_fit is not None
    assert merged.goal_fit.problems == ("drifted", "overwhelming")
    assert classify(ExecutionReport(ok=True), merged).category == (
        FailureCategory.BLOCKER_STRUCTURE
    )


@pytest.mark.unit
def test_the_student_parse_step_preserves_the_verdict(tmp_path: Path) -> None:
    """The seam where a key silently disappears: parse → re-dump → artifact.

    `_parse_grade_report` rebuilds the report JSON (it derives quality_score from the
    rubric and stamps `graded`), so a field it does not know about is exactly the kind
    of thing that gets dropped on the way to disk. It reaches the classifier only if it
    survives this round trip.
    """
    from forged.pipeline.agents.student import StudentAgent

    personas = tmp_path / "personas"
    personas.mkdir(exist_ok=True)
    (personas / "student.md").write_text("You are the Student.", encoding="utf-8")
    agent = StudentAgent(personas_dir=personas)

    raw = json.dumps(
        {
            "quality_score": 90.0,
            "rubric": {
                "structure": 90.0,
                "explanation_depth": 90.0,
                "code_clarity": 90.0,
                "correctness": 90.0,
                "learner_fit": 90.0,
            },
            "verdict": "Clear, and far too much of it.",
            "goal_fit": {
                "fit": False,
                "problems": ["overwhelming"],
                "text": "Six helper classes the learner never touches again.",
            },
            "blockers": [],
            "findings": [],
        }
    )

    report_json, graded = agent._parse_grade_report(raw)

    assert graded is True
    assert json.loads(report_json)["goal_fit"]["problems"] == ["overwhelming"]
