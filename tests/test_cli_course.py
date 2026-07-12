"""CLI tests for `forged course --plan-only` (doc 13, Phase 1e).

Phase 1 ships the plan-only slice: decompose a brief into a CourseSpec and check the
union-coverage honesty invariant — no module runs. Tests patch the CurriculumPlanner so
they never hit the network; they assert the CLI plumbing, the fidelity verdict, and the
honest exit codes.
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

    code = cli.main(["course", "--topic", "quantum teleportation", "--plan-only"])

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

    code = cli.main(["course", "--topic", "quantum teleportation", "--plan-only"])

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
        ["course", "--topic", "quantum teleportation", "--plan-only", "--out", str(out)]
    )

    assert code == cli.EXIT_OK
    plan = json.loads((out / "course_plan.json").read_text())
    assert plan["course"]["title"] == "Quantum teleportation course"
    assert len(plan["course"]["modules"]) == 2
    assert plan["fidelity"]["is_faithful"] is True
    assert "Foundations" in (out / "COURSE.md").read_text()


@pytest.mark.unit
def test_course_empty_topic_is_usage_error() -> None:
    code = cli.main(["course", "--topic", "   ", "--plan-only"])
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
        ["course", "--topic", "quantum teleportation", "--runs", str(tmp_path)]
    )

    assert code == cli.EXIT_OK
    assert captured["course"] is course  # orchestration actually ran


@pytest.mark.unit
def test_course_threads_max_modules_and_no_provision(monkeypatch, tmp_path) -> None:
    course = _faithful_course()
    _patch_planner(monkeypatch, course)
    captured = _patch_run_course(monkeypatch, _module_result(course, terminal_ok=True))

    cli.main(
        ["course", "--topic", "quantum teleportation", "--runs", str(tmp_path),
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
        ["course", "--topic", "quantum teleportation", "--runs", str(tmp_path)]
    )
    assert code == cli.EXIT_RUNTIME


@pytest.mark.unit
def test_course_fidelity_failure_blocks_orchestration(monkeypatch, tmp_path) -> None:
    # Course covers nothing about the topic → never orchestrate.
    dropped = CourseSpec(
        title="Unrelated", modules=(_module("Apples", ["learn about apples"], [], 0),),
        rationale="",
    )
    _patch_planner(monkeypatch, dropped)
    ran = {"called": False}

    def _fake(*a, **k):
        ran["called"] = True
        return _module_result(dropped, True)
    monkeypatch.setattr(orch, "run_course", _fake)

    code = cli.main(
        ["course", "--topic", "quantum teleportation", "--runs", str(tmp_path)]
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
        ["course", "--topic", "quantum teleportation", "--runs", str(tmp_path),
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
        ["course", "--topic", "quantum teleportation", "--runs", str(tmp_path)]
    )

    assert code == cli.EXIT_OK
    assert "max_depth" not in captured["kwargs"]  # sequential path, no reactive kwargs
