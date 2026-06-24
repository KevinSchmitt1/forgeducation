"""CLI tests for `forged course --plan-only` (doc 13, Phase 1e).

Phase 1 ships the plan-only slice: decompose a brief into a CourseSpec and check the
union-coverage honesty invariant — no module runs. Tests patch the CurriculumPlanner so
they never hit the network; they assert the CLI plumbing, the fidelity verdict, and the
honest exit codes.
"""

from __future__ import annotations

import pytest

import forged.cli as cli
from forged.curriculum.model import CourseSpec, ModuleSpec
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
def test_course_requires_plan_only_flag_in_phase_1(monkeypatch) -> None:
    _patch_planner(monkeypatch, CourseSpec(title="x", modules=(), rationale=""))
    code = cli.main(["course", "--topic", "anything"])
    assert code == cli.EXIT_USAGE


@pytest.mark.unit
def test_course_empty_topic_is_usage_error() -> None:
    code = cli.main(["course", "--topic", "   ", "--plan-only"])
    assert code == cli.EXIT_USAGE
