"""CLI tests for the course path through `forged learn` (doc 13).

These originally drove a separate `forged course` command. That command is gone — one
front door plans first and decides lesson-vs-course itself — so they now drive `learn`
with a planner stubbed to return a multi-module CourseSpec, which is exactly how the
course path is reached in production. The behaviour under test is unchanged: the
plan-only slice, the union-coverage honesty invariant, the orchestration hand-off, and
the honest exit codes.

Every course here has ≥2 modules, so the readiness pre-flight (1-module only) never
fires and no ReadinessAssessor stub is needed. Tests patch the CurriculumPlanner so they
never hit the network.
"""

from __future__ import annotations

import pytest

import forged.cli as cli
import forged.curriculum.orchestrator as orch
from forged.curriculum.model import CourseResult, CourseSpec, ModuleResult, ModuleSpec
from forged.models import TopicSpecification


def _module(title: str, objectives: list[str], focus: list[str], order: int) -> ModuleSpec:
    return ModuleSpec(
        spec=TopicSpecification(
            title=title,
            scope="implementation",
            learning_objectives=objectives,
            prerequisites=[],
            constraints="",
            depth="intermediate",
            focus_areas=focus,
        ),
        order=order,
    )


class _FakePlanner:
    """Stand-in for CurriculumPlanner that returns a preset CourseSpec without an LLM."""

    course: CourseSpec

    def __init__(self, *args, **kwargs) -> None:
        pass

    def plan(self, brief, learner_profile, topic_spec=None) -> CourseSpec:
        return type(self).course


def _patch_planner(monkeypatch, course: CourseSpec) -> None:
    _FakePlanner.course = course
    monkeypatch.setattr(cli, "CurriculumPlanner", _FakePlanner, raising=False)


class _FakeAssessor:
    """ReadinessAssessor stand-in: always reachable, never a network call."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def assess(self, **kwargs):
        from forged.curriculum.model import ReadinessVerdict

        return ReadinessVerdict(
            reachable=True,
            beachhead="",
            missing_foundations=(),
            unreachable_capabilities=(),
            reason="stubbed",
        )


@pytest.fixture(autouse=True)
def _no_live_calls(monkeypatch):
    """Hard guard: nothing in this file may reach a real LLM or a real pipeline.

    `learn` reaches two things `course` never did — the ReadinessAssessor (1-module plans
    only) and the single-lesson branch. Both construct real LLM clients. A test here that
    forgets to stub them does not fail; it runs a full paid pipeline for ~10 minutes and
    then fails on the assertion. Stubbing them autouse makes that impossible rather than
    merely discouraged.
    """
    monkeypatch.setattr(cli, "ReadinessAssessor", _FakeAssessor, raising=False)

    def _refuse_single_lesson(**kwargs):
        raise AssertionError(
            "the single-lesson branch was reached in a course-path test; "
            "if that is intended, assert on it explicitly with an explicit stub"
        )

    monkeypatch.setattr(cli, "_run_agentic_lesson", _refuse_single_lesson)


@pytest.mark.unit
def test_course_plan_only_prints_modules_and_exits_ok(monkeypatch, capsys) -> None:
    # A faithful course for the default topic spec (objective "Understand <topic>",
    # focus "<topic>"): the union mentions the topic terms.
    course = CourseSpec(
        title="Quantum teleportation course",
        modules=(
            _module("Foundations", ["Understand quantum teleportation basics"], [], 0),
            _module("Practice", ["apply quantum teleportation protocols"], [], 1),
        ),
        rationale="split foundations from practice",
    )
    _patch_planner(monkeypatch, course)

    code = cli.main(["learn", "--topic", "quantum teleportation", "--plan-only"])

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "Foundations" in out and "Practice" in out
    assert "2 module" in out  # a module count is reported


@pytest.mark.unit
def test_course_plan_only_warns_on_dropped_capability(monkeypatch, capsys) -> None:
    # Course covers nothing about the topic → union-coverage check fails honestly.
    course = CourseSpec(
        title="Unrelated",
        modules=(_module("Apples", ["learn about apples"], [], 0),),
        rationale="oops, dropped the topic",
    )
    _patch_planner(monkeypatch, course)

    code = cli.main(["learn", "--topic", "quantum teleportation", "--plan-only"])

    err = capsys.readouterr().err
    assert code == cli.EXIT_RUNTIME
    assert "quantum teleportation" in err.lower()


@pytest.mark.unit
def test_course_plan_only_persists_to_out_dir(monkeypatch, tmp_path) -> None:
    import json

    course = CourseSpec(
        title="Quantum teleportation course",
        modules=(
            _module("Foundations", ["Understand quantum teleportation basics"], [], 0),
            _module("Practice", ["apply quantum teleportation protocols"], [], 1),
        ),
        rationale="split foundations from practice",
    )
    _patch_planner(monkeypatch, course)

    out = tmp_path / "course"
    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--plan-only", "--out", str(out)]
    )

    assert code == cli.EXIT_OK
    plan = json.loads((out / "course_plan.json").read_text())
    assert plan["course"]["title"] == "Quantum teleportation course"
    assert len(plan["course"]["modules"]) == 2
    assert plan["fidelity"]["is_faithful"] is True
    assert "Foundations" in (out / "COURSE.md").read_text()


@pytest.mark.unit
def test_course_empty_topic_is_usage_error() -> None:
    code = cli.main(["learn", "--topic", "   ", "--plan-only"])
    assert code == cli.EXIT_USAGE


# ── orchestration path (no --plan-only) ───────────────────────────────────────


def _faithful_course() -> CourseSpec:
    return CourseSpec(
        title="Quantum teleportation course",
        modules=(
            _module("Foundations", ["Understand quantum teleportation basics"], [], 0),
            _module("Practice", ["apply quantum teleportation protocols"], [], 1),
        ),
        rationale="split",
    )


def _patch_run_course(monkeypatch, result: CourseResult) -> dict:
    """Patch the orchestrator's run_course; capture the kwargs it was called with."""
    captured: dict = {}

    def _fake(course, learner_profile, course_dir, **kwargs):
        captured["course"] = course
        captured["kwargs"] = kwargs
        return result
    monkeypatch.setattr(orch, "run_course", _fake)
    return captured


def _module_result(course: CourseSpec, terminal_ok: bool) -> CourseResult:
    return CourseResult(
        course=course,
        modules=tuple(
            ModuleResult(
                module=m, run_dir=f"/tmp/m{m.order}", terminal_ok=terminal_ok,
                notebook_path=f"/tmp/m{m.order}/lesson.ipynb" if terminal_ok else None,
                topic_fidelity=(),
            )
            for m in course.modules
        ),
    )


@pytest.mark.unit
def test_course_without_plan_only_invokes_orchestrator(monkeypatch, tmp_path) -> None:
    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    captured = _patch_run_course(monkeypatch, _module_result(course, terminal_ok=True))

    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes"]
    )

    assert code == cli.EXIT_OK
    assert captured["course"] is course  # orchestration actually ran


@pytest.mark.unit
def test_course_run_writes_post_run_readme_and_course_md(monkeypatch, tmp_path) -> None:
    """After orchestration, the course directory carries the assembled deliverable
    (doc 13, Phase 3) — not just the pre-run COURSE.md preview from `_persist_course`."""
    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    _patch_run_course(monkeypatch, _module_result(course, terminal_ok=True))

    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes"]
    )

    assert code == cli.EXIT_OK
    course_dirs = list(tmp_path.glob("*_course_*"))
    assert len(course_dirs) == 1
    course_dir = course_dirs[0]
    assert (course_dir / "README.md").is_file()
    assert "Foundations" in (course_dir / "README.md").read_text()
    assert (course_dir / "COURSE.md").is_file()
    assert "Quantum teleportation course" in (course_dir / "COURSE.md").read_text()


@pytest.mark.unit
def test_course_threads_max_modules_and_no_provision(monkeypatch, tmp_path) -> None:
    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    captured = _patch_run_course(monkeypatch, _module_result(course, terminal_ok=True))

    cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes",
         "--max-modules", "1", "--no-provision"]
    )

    assert captured["kwargs"]["max_modules"] == 1
    assert captured["kwargs"]["provision"] is False


@pytest.mark.unit
def test_course_with_failed_module_exits_runtime(monkeypatch, tmp_path) -> None:
    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    _patch_run_course(monkeypatch, _module_result(course, terminal_ok=False))

    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes"]
    )
    assert code == cli.EXIT_RUNTIME


@pytest.mark.unit
def test_course_fidelity_failure_blocks_orchestration(monkeypatch, tmp_path) -> None:
    # Course covers nothing about the topic → never orchestrate. Two modules, so the plan
    # takes the course branch (a 1-module plan is a single lesson, where R1's lesson-level
    # detector owns fidelity instead).
    dropped = CourseSpec(
        title="Unrelated",
        modules=(
            _module("Apples", ["learn about apples"], [], 0),
            _module("Oranges", ["learn about oranges"], [], 1),
        ),
        rationale="",
    )
    _patch_planner(monkeypatch, dropped)
    ran = {"called": False}

    def _fake(*a, **k):
        ran["called"] = True
        return _module_result(dropped, True)
    monkeypatch.setattr(orch, "run_course", _fake)

    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes"]
    )
    assert code == cli.EXIT_RUNTIME
    assert ran["called"] is False


# ── reactive safety net (--redecompose) routing (doc 13, Phase 4) ──────────────


@pytest.mark.unit
def test_redecompose_routes_to_reactive_loop_and_threads_max_depth(monkeypatch, tmp_path) -> None:
    import forged.curriculum.reactive as reactive

    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    captured: dict = {}

    def _fake_reactive(course_, learner_profile, course_dir, **kwargs):
        captured["kwargs"] = kwargs
        return _module_result(course_, terminal_ok=True)

    # If it wrongly took the sequential path this would raise (run_course not stubbed).
    monkeypatch.setattr(reactive, "run_course_reactive", _fake_reactive)
    monkeypatch.setattr(cli, "_make_remediation_planner", lambda personas_dir: object())

    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes",
         "--redecompose", "--max-depth", "3"]
    )

    assert code == cli.EXIT_OK
    assert captured["kwargs"]["max_depth"] == 3
    assert "plan_remediation" in captured["kwargs"]


@pytest.mark.unit
def test_without_redecompose_uses_sequential_run_course(monkeypatch, tmp_path) -> None:
    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    captured = _patch_run_course(monkeypatch, _module_result(course, terminal_ok=True))

    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path), "--yes"]
    )

    assert code == cli.EXIT_OK
    assert "max_depth" not in captured["kwargs"]  # sequential path, no reactive kwargs


# ── The course path gates before spending (doc 18, D3/Phase 5) ────────────────────


@pytest.mark.unit
def test_course_without_yes_on_a_non_tty_is_a_usage_error(monkeypatch, tmp_path, capsys):
    """`course` used to spend on module builds with no confirmation at all — the
    2026-07-28 run built four paid modules nobody had reviewed (doc 18, E5)."""
    # Arrange
    import sys as _sys

    _patch_planner(monkeypatch, _faithful_course())
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)

    # Act
    code = cli.main(
        ["learn", "--topic", "quantum teleportation", "--runs", str(tmp_path)]
    )

    # Assert — no TTY and no --yes means nothing paid runs.
    assert code == cli.EXIT_USAGE
    assert "--yes" in capsys.readouterr().err


# ── --plan-only must show what the gate shows ─────────────────────────────────────
#
# Three renderers existed for one plan: render_plan (the gate), _print_course (plan-only
# stdout) and _render_course_md (COURSE.md). Only the gate showed each module's
# lesson_mode, so `--plan-only` — the cheap path whose entire job is telling you what a
# build would be before you pay for it — hid the one field you probe for. The mode was
# in course_plan.json the whole time, just never rendered.


def _artifact_module(title: str, objectives: list[str], order: int) -> ModuleSpec:
    return ModuleSpec(
        spec=TopicSpecification(
            title=title,
            scope="implementation",
            learning_objectives=objectives,
            prerequisites=[],
            constraints="",
            depth="intermediate",
            focus_areas=[],
        ),
        order=order,
        lesson_mode="artifact",
    )


@pytest.mark.unit
def test_plan_only_stdout_shows_each_modules_lesson_mode(monkeypatch, capsys) -> None:
    course = CourseSpec(
        title="Copilot config course",
        modules=(_artifact_module("Write the files", ["Understand quantum teleportation"], 0),),
        rationale="one focused session",
    )
    _patch_planner(monkeypatch, course)

    code = cli.main(["learn", "--topic", "quantum teleportation", "--plan-only"])

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "artifact" in out


@pytest.mark.unit
def test_plan_only_stdout_shows_what_a_build_would_cost(monkeypatch, capsys) -> None:
    """The cheap path should price the expensive one — that is what it is for."""
    course = CourseSpec(
        title="Copilot config course",
        modules=(_artifact_module("Write the files", ["Understand quantum teleportation"], 0),),
        rationale="one focused session",
    )
    _patch_planner(monkeypatch, course)

    cli.main(["learn", "--topic", "quantum teleportation", "--plan-only"])

    assert "Estimated cost" in capsys.readouterr().out


@pytest.mark.unit
def test_course_md_records_the_lesson_mode(monkeypatch, tmp_path) -> None:
    course = CourseSpec(
        title="Copilot config course",
        modules=(_artifact_module("Write the files", ["Understand quantum teleportation"], 0),),
        rationale="one focused session",
    )
    _patch_planner(monkeypatch, course)

    out = tmp_path / "course"
    cli.main(
        ["learn", "--topic", "quantum teleportation", "--plan-only", "--out", str(out)]
    )

    assert "artifact" in (out / "COURSE.md").read_text()
