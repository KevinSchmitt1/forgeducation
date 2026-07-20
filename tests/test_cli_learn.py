"""CLI tests for `forged learn` — the smart front door (doc 16, Phase 5).

The command always sizes with the CurriculumPlanner, gates on confirmation, then builds
either a single lesson (1 module) or a course (N modules). Tests patch the planner, the
gate, and both build paths so nothing hits the network or spends: they assert the plumbing,
the branch selection, and the honest exit codes.
"""

from __future__ import annotations

import pytest

import forged.cli as cli
import forged.curriculum.gate as gate_mod
import forged.curriculum.orchestrator as orch
from forged.curriculum.gate import GateOutcome
from forged.curriculum.model import (
    CourseResult,
    CourseSpec,
    ModuleResult,
    ModuleSpec,
    ReadinessVerdict,
)
from forged.models import TopicSpecification


def _module(title: str, order: int) -> ModuleSpec:
    return ModuleSpec(
        spec=TopicSpecification(
            title=title,
            scope="implementation",
            learning_objectives=[f"do {title}"],
            prerequisites=[],
            constraints="",
            depth="intermediate",
            focus_areas=[title],
        ),
        order=order,
    )


def _course(*titles: str) -> CourseSpec:
    return CourseSpec(
        title="A course",
        modules=tuple(_module(t, i) for i, t in enumerate(titles)),
        rationale="r",
    )


class _FakePlanner:
    """Returns a preset CourseSpec; accepts the guidance kwarg the gate's replanner uses."""

    course: CourseSpec

    def __init__(self, *args, **kwargs) -> None:
        pass

    def plan(self, brief, learner_profile, topic_spec=None, guidance=None) -> CourseSpec:
        return type(self).course


def _patch_planner(monkeypatch, course: CourseSpec) -> None:
    _FakePlanner.course = course
    monkeypatch.setattr(cli, "CurriculumPlanner", _FakePlanner, raising=False)


class _FakeEscalatingPlanner:
    """Like _FakePlanner, but returns a different CourseSpec when `guidance` is set —
    for exercising the readiness pre-flight's escalation re-plan (doc 14, Part III)."""

    base_course: CourseSpec
    escalated_course: CourseSpec
    guidance_seen: list[str]

    def __init__(self, *args, **kwargs) -> None:
        pass

    def plan(self, brief, learner_profile, topic_spec=None, guidance=None) -> CourseSpec:
        if guidance:
            type(self).guidance_seen.append(guidance)
            return type(self).escalated_course
        return type(self).base_course


def _patch_escalating_planner(
    monkeypatch, base_course: CourseSpec, escalated_course: CourseSpec
) -> list[str]:
    _FakeEscalatingPlanner.base_course = base_course
    _FakeEscalatingPlanner.escalated_course = escalated_course
    _FakeEscalatingPlanner.guidance_seen = []
    monkeypatch.setattr(cli, "CurriculumPlanner", _FakeEscalatingPlanner, raising=False)
    return _FakeEscalatingPlanner.guidance_seen


_REACHABLE_VERDICT = ReadinessVerdict(
    reachable=True, beachhead="", missing_foundations=(),
    unreachable_capabilities=(), reason="",
)


class _FakeAssessor:
    """Stand-in for ReadinessAssessor — never touches the network. CRITICAL: every test
    that reaches `_cmd_learn`'s readiness pre-flight must patch this, or an un-mocked
    1-module course will construct a REAL ReadinessAssessor and make a live, paid OpenAI
    call (this bit us once — see PR history)."""

    verdict: ReadinessVerdict
    instances: list[_FakeAssessor]

    def __init__(self, *args, **kwargs) -> None:
        type(self).instances.append(self)

    def assess(self, brief, learner_profile, topic_spec=None) -> ReadinessVerdict:
        return type(self).verdict


def _patch_assessor(
    monkeypatch, verdict: ReadinessVerdict = _REACHABLE_VERDICT
) -> list[_FakeAssessor]:
    _FakeAssessor.verdict = verdict
    _FakeAssessor.instances = []
    monkeypatch.setattr(cli, "ReadinessAssessor", _FakeAssessor, raising=False)
    return _FakeAssessor.instances


class _FakeStdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _patch_stdin(monkeypatch, tty: bool) -> None:
    monkeypatch.setattr(cli.sys, "stdin", _FakeStdin(tty))


def _patch_gate(monkeypatch, confirmed: bool, course: CourseSpec) -> None:
    def _fake_gate(course_arg, caps, adjuster, replanner, input_stream, output_stream, **kw):
        return GateOutcome(confirmed=confirmed, course=course, rounds_used=1)

    monkeypatch.setattr(gate_mod, "run_gate", _fake_gate)


def _patch_single_lesson(monkeypatch) -> dict:
    captured: dict = {}

    def _fake(**kwargs):
        captured.update(kwargs)
        return cli.EXIT_OK

    monkeypatch.setattr(cli, "_run_agentic_lesson", _fake)
    return captured


def _patch_run_course(monkeypatch, course: CourseSpec) -> dict:
    captured: dict = {}

    def _fake(course_arg, learner_profile, course_dir, **kwargs):
        captured["course"] = course_arg
        captured["kwargs"] = kwargs
        return CourseResult(
            course=course_arg,
            modules=tuple(
                ModuleResult(
                    module=m, run_dir=f"/tmp/m{m.order}", terminal_ok=True,
                    notebook_path=f"/tmp/m{m.order}/lesson.ipynb", topic_fidelity=(),
                )
                for m in course_arg.modules
            ),
        )

    monkeypatch.setattr(orch, "run_course", _fake)
    return captured


# ── branch selection ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_one_module_confirm_invokes_single_lesson(monkeypatch, tmp_path) -> None:
    course = _course("Just one thing")
    _patch_planner(monkeypatch, course)
    _patch_assessor(monkeypatch)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=True, course=course)
    single = _patch_single_lesson(monkeypatch)
    course_ran = _patch_run_course(monkeypatch, course)

    code = cli.main(["learn", "--topic", "one thing", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert single["topic_spec"].title == "Just one thing"  # single-lesson path used
    assert "course" not in course_ran  # run_course NOT invoked


@pytest.mark.unit
def test_multi_module_confirm_invokes_run_course(monkeypatch, tmp_path) -> None:
    course = _course("Setup", "Train")
    _patch_planner(monkeypatch, course)
    _patch_assessor(monkeypatch)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=True, course=course)
    single = _patch_single_lesson(monkeypatch)
    course_ran = _patch_run_course(monkeypatch, course)

    code = cli.main(["learn", "--topic", "setup and train", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert course_ran["course"] is course  # course orchestration used
    assert single == {}  # single-lesson path NOT invoked


@pytest.mark.unit
def test_yes_skips_gate_and_builds(monkeypatch, tmp_path) -> None:
    course = _course("Solo")
    _patch_planner(monkeypatch, course)
    _patch_assessor(monkeypatch)

    def _boom(*a, **k):  # the gate must never run under --yes
        raise AssertionError("run_gate should not be called with --yes")

    monkeypatch.setattr(gate_mod, "run_gate", _boom)
    single = _patch_single_lesson(monkeypatch)

    code = cli.main(["learn", "--topic", "solo", "--yes", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert single["topic_spec"].title == "Solo"


@pytest.mark.unit
def test_non_tty_without_yes_is_usage_error(monkeypatch, tmp_path, capsys) -> None:
    course = _course("Solo")
    _patch_planner(monkeypatch, course)
    _patch_assessor(monkeypatch)
    _patch_stdin(monkeypatch, tty=False)
    single = _patch_single_lesson(monkeypatch)

    code = cli.main(["learn", "--topic", "solo", "--runs", str(tmp_path)])

    assert code == cli.EXIT_USAGE
    assert "TTY" in capsys.readouterr().err
    assert single == {}  # nothing built


@pytest.mark.unit
def test_cancel_exits_ok_without_running(monkeypatch, tmp_path, capsys) -> None:
    course = _course("Setup", "Train")
    _patch_planner(monkeypatch, course)
    _patch_assessor(monkeypatch)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=False, course=course)
    single = _patch_single_lesson(monkeypatch)
    course_ran = _patch_run_course(monkeypatch, course)

    code = cli.main(["learn", "--topic", "setup and train", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK  # a deliberate 'no' is success
    assert "Nothing was run" in capsys.readouterr().out
    assert single == {} and "course" not in course_ran  # neither path ran


@pytest.mark.unit
def test_empty_topic_is_usage_error() -> None:
    assert cli.main(["learn", "--topic", "   "]) == cli.EXIT_USAGE


@pytest.mark.unit
def test_max_modules_and_no_provision_threaded_to_run_course(monkeypatch, tmp_path) -> None:
    course = _course("Setup", "Train", "Serve")
    _patch_planner(monkeypatch, course)
    _patch_assessor(monkeypatch)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=True, course=course)
    course_ran = _patch_run_course(monkeypatch, course)

    cli.main(
        ["learn", "--topic", "x", "--runs", str(tmp_path),
         "--max-modules", "1", "--no-provision"]
    )

    assert course_ran["kwargs"]["max_modules"] == 1
    assert course_ran["kwargs"]["provision"] is False


# ── readiness pre-flight (doc 14, Part III) ───────────────────────────────────────

_NOT_REACHABLE_VERDICT = ReadinessVerdict(
    reachable=False,
    beachhead="load a pretrained model and generate text",
    missing_foundations=("what a tensor is",),
    unreachable_capabilities=("fine-tune with LoRA",),
    reason="requires prerequisites the learner lacks: tensors",
)


@pytest.mark.unit
def test_one_module_reachable_skips_escalation_assessor_called_once(
    monkeypatch, tmp_path
) -> None:
    course = _course("Just one thing")
    _patch_planner(monkeypatch, course)
    instances = _patch_assessor(monkeypatch, _REACHABLE_VERDICT)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=True, course=course)
    single = _patch_single_lesson(monkeypatch)

    code = cli.main(["learn", "--topic", "one thing", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert single["topic_spec"].title == "Just one thing"  # no escalation happened
    assert len(instances) == 1  # assessor called exactly once


@pytest.mark.unit
def test_one_module_not_reachable_escalates_with_guidance_and_shows_gate(
    monkeypatch, tmp_path
) -> None:
    base_course = _course("Just one thing")
    escalated_course = _course("Foundations", "Just one thing")
    guidance_seen = _patch_escalating_planner(monkeypatch, base_course, escalated_course)
    _patch_assessor(monkeypatch, _NOT_REACHABLE_VERDICT)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=True, course=escalated_course)
    course_ran = _patch_run_course(monkeypatch, escalated_course)

    code = cli.main(["learn", "--topic", "one thing", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert course_ran["course"] is escalated_course  # escalated course was built
    assert len(guidance_seen) == 1
    assert "tensors" in guidance_seen[0]  # missing foundations reached the re-plan


@pytest.mark.unit
def test_n_module_plan_never_calls_the_assessor(monkeypatch, tmp_path) -> None:
    course = _course("Setup", "Train")
    _patch_planner(monkeypatch, course)
    instances = _patch_assessor(monkeypatch, _NOT_REACHABLE_VERDICT)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=True, course=course)
    _patch_run_course(monkeypatch, course)

    code = cli.main(["learn", "--topic", "setup and train", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert instances == []  # pre-flight is 1-module-only


@pytest.mark.unit
def test_yes_and_not_reachable_escalates_and_skips_gate(monkeypatch, tmp_path) -> None:
    base_course = _course("Solo")
    escalated_course = _course("Foundations", "Solo")
    _patch_escalating_planner(monkeypatch, base_course, escalated_course)
    _patch_assessor(monkeypatch, _NOT_REACHABLE_VERDICT)

    def _boom(*a, **k):  # the gate must never run under --yes, even after escalation
        raise AssertionError("run_gate should not be called with --yes")

    monkeypatch.setattr(gate_mod, "run_gate", _boom)
    course_ran = _patch_run_course(monkeypatch, escalated_course)

    code = cli.main(["learn", "--topic", "solo", "--yes", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK
    assert course_ran["course"] is escalated_course


@pytest.mark.unit
def test_non_tty_without_yes_on_escalation_is_usage_error(
    monkeypatch, tmp_path, capsys
) -> None:
    base_course = _course("Solo")
    escalated_course = _course("Foundations", "Solo")
    _patch_escalating_planner(monkeypatch, base_course, escalated_course)
    _patch_assessor(monkeypatch, _NOT_REACHABLE_VERDICT)
    _patch_stdin(monkeypatch, tty=False)
    single = _patch_single_lesson(monkeypatch)

    code = cli.main(["learn", "--topic", "solo", "--runs", str(tmp_path)])

    assert code == cli.EXIT_USAGE
    assert "TTY" in capsys.readouterr().err
    assert single == {}  # nothing built


@pytest.mark.unit
def test_cancel_after_escalation_exits_ok_without_running(
    monkeypatch, tmp_path, capsys
) -> None:
    base_course = _course("Solo")
    escalated_course = _course("Foundations", "Solo")
    _patch_escalating_planner(monkeypatch, base_course, escalated_course)
    _patch_assessor(monkeypatch, _NOT_REACHABLE_VERDICT)
    _patch_stdin(monkeypatch, tty=True)
    _patch_gate(monkeypatch, confirmed=False, course=escalated_course)
    single = _patch_single_lesson(monkeypatch)
    course_ran = _patch_run_course(monkeypatch, escalated_course)

    code = cli.main(["learn", "--topic", "solo", "--runs", str(tmp_path)])

    assert code == cli.EXIT_OK  # a deliberate 'no' is success
    assert "Nothing was run" in capsys.readouterr().out
    assert single == {} and "course" not in course_ran  # neither path ran
