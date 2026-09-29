"""Service layer behind the UI front door (doc 25, Lane 8).

The service is the UI's only door into the backend: plan → preview → edit/adjust →
build. Every LLM here is a scripted stub (`_ScriptedLLM`), and the launcher is a fake,
so nothing reaches the network or spends. The BYOK key contract — held in memory,
handed to the build via its environment, never on disk, never logged — is tested
directly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pytest

import forged.cli as cli
import forged.service as service
from forged.curriculum.model import course_from_dict
from forged.service import (
    BuildOptions,
    ForgeService,
    RunInputs,
    inputs_from_dict,
    inputs_to_dict,
)

SECRET = "sk-test-SECRET-do-not-leak-1234567890"


def _module_json(title: str, mode: str = "executable", prereqs: list[str] | None = None) -> dict:
    return {
        "title": title,
        "scope": "implementation",
        "depth": "intermediate",
        "learning_objectives": [f"Do {title}"],
        "prerequisites": [],
        "focus_areas": [title],
        "module_prerequisites": prereqs or [],
        "lesson_mode": mode,
    }


def _plan_json(*titles: str, modes: tuple[str, ...] = ()) -> str:
    modules = [
        _module_json(t, modes[i] if i < len(modes) else "executable")
        for i, t in enumerate(titles)
    ]
    return json.dumps({"title": "A course", "rationale": "because", "modules": modules})


class _ScriptedLLM:
    """Answers by response-format name; records every call (and the env key it saw)."""

    def __init__(self, replies: dict[str, list[str]]) -> None:
        self._replies = {k: list(v) for k, v in replies.items()}
        self.calls: list[tuple[str, str]] = []
        self.keys_seen: list[str | None] = []

    def complete(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
        name = kwargs["response_format"]["json_schema"]["name"]
        self.calls.append((name, user_prompt))
        self.keys_seen.append(os.environ.get("OPENAI_API_KEY"))
        queue = self._replies[name]
        return queue.pop(0) if len(queue) > 1 else queue[0]


_REACHABLE = json.dumps(
    {
        "reachable": True,
        "beachhead": "",
        "missing_foundations": [],
        "unreachable_capabilities": [],
        "reason": "fine",
    }
)


def _intent(op: str, targets: list[int], instruction: str = "") -> str:
    return json.dumps({"op": op, "targets": targets, "instruction": instruction})


class _FakeLauncher:
    def __init__(self) -> None:
        self.launched: list[dict[str, Any]] = []

    def launch(self, command, env_overrides, log_path, cwd):
        self.launched.append(
            {"command": tuple(command), "env": dict(env_overrides), "log": log_path, "cwd": cwd}
        )
        return 4242

    def poll(self, pid):
        return None


def _inputs(topic: str = "Hash maps") -> RunInputs:
    return inputs_from_dict(
        {
            "topic": topic,
            "learner_profile": {
                "name": "Ada",
                "description": "d",
                "prior_knowledge": ["Python"],
                "environment": "jupyter_notebook",
                "material_density": "standard",
                "learning_style": "hands_on",
                "background_context": "b",
            },
            "topic_spec": {
                "title": topic,
                "scope": "implementation",
                "depth": "intermediate",
                "learning_objectives": ["Build a hash map", "Resolve collisions"],
                "prerequisites": [],
                "focus_areas": [],
                "constraints": "",
            },
        }
    )


def _service(tmp_path: Path, llm: _ScriptedLLM | None = None, launcher=None) -> ForgeService:
    scripted = llm or _ScriptedLLM({})
    return ForgeService(
        personas_dir=cli.DEFAULT_PERSONAS,
        runs_root=tmp_path / "runs",
        llm_factory=lambda _model: scripted,
        launcher=launcher or _FakeLauncher(),
    )


# ── Input validation at the boundary ────────────────────────────────────────────────


@pytest.mark.unit
def test_inputs_round_trip_through_a_plain_dict() -> None:
    inputs = _inputs()

    again = inputs_from_dict(inputs_to_dict(inputs))

    assert again == inputs


@pytest.mark.unit
def test_invalid_inputs_report_every_problem_with_its_field() -> None:
    bad = inputs_to_dict(_inputs())
    bad = {
        **bad,
        "topic": "   ",
        "learner_profile": {**bad["learner_profile"], "material_density": "medium"},
        "topic_spec": {**bad["topic_spec"], "scope": "everything"},
    }

    with pytest.raises(service.InputError) as excinfo:
        inputs_from_dict(bad)

    problems = excinfo.value.problems
    assert any("topic" in p for p in problems)
    assert any("material_density" in p and "medium" in p for p in problems)
    assert any("scope" in p and "everything" in p for p in problems)


@pytest.mark.unit
def test_blank_list_rows_are_dropped_and_blank_title_falls_back_to_topic() -> None:
    raw = inputs_to_dict(_inputs("Tries"))
    raw = {
        **raw,
        "topic_spec": {
            **raw["topic_spec"],
            "title": " ",
            "learning_objectives": ["", "  Insert a key ", "   "],
        },
    }

    inputs = inputs_from_dict(raw)

    assert inputs.topic_spec.title == "Tries"
    assert inputs.topic_spec.learning_objectives == ["Insert a key"]


@pytest.mark.unit
def test_no_objectives_falls_back_to_the_cli_default() -> None:
    raw = inputs_to_dict(_inputs("Tries"))
    raw = {**raw, "topic_spec": {**raw["topic_spec"], "learning_objectives": []}}

    inputs = inputs_from_dict(raw)

    assert inputs.topic_spec.learning_objectives == ["Understand Tries"]


@pytest.mark.unit
def test_a_list_field_given_as_a_string_is_rejected_not_split_into_characters() -> None:
    raw = inputs_to_dict(_inputs())
    raw = {**raw, "learner_profile": {**raw["learner_profile"], "prior_knowledge": "Python"}}

    with pytest.raises(service.InputError, match="prior_knowledge"):
        inputs_from_dict(raw)


@pytest.mark.unit
def test_default_inputs_match_the_cli_defaults() -> None:
    inputs = service.default_inputs("Graphs")

    assert inputs.learner_profile == cli._default_learner_profile()
    assert inputs.topic_spec == cli._default_topic_spec("Graphs")


# ── plan → preview ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_plan_returns_a_json_safe_course_dict(tmp_path: Path) -> None:
    llm = _ScriptedLLM({"course_plan": [_plan_json("Arrays", "Hashing", "Collisions")]})

    plan = _service(tmp_path, llm).plan(_inputs())

    json.dumps(plan)  # must cross the UI seam as JSON
    assert [m["spec"]["title"] for m in plan["modules"]] == ["Arrays", "Hashing", "Collisions"]
    assert [name for name, _ in llm.calls] == ["course_plan"]  # N modules: no readiness call


@pytest.mark.unit
def test_single_module_plan_runs_the_readiness_preflight(tmp_path: Path) -> None:
    llm = _ScriptedLLM(
        {"course_plan": [_plan_json("Hash maps")], "readiness_verdict": [_REACHABLE]}
    )

    plan = _service(tmp_path, llm).plan(_inputs())

    assert len(plan["modules"]) == 1
    assert [name for name, _ in llm.calls] == ["course_plan", "readiness_verdict"]


@pytest.mark.unit
def test_plan_uses_the_byok_key_only_for_the_duration_of_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = _ScriptedLLM({"course_plan": [_plan_json("A", "B")]})

    _service(tmp_path, llm).plan(_inputs(), api_key=SECRET)

    assert llm.keys_seen == [SECRET]
    assert "OPENAI_API_KEY" not in os.environ


@pytest.mark.unit
def test_plan_restores_a_pre_existing_environment_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    llm = _ScriptedLLM({"course_plan": [_plan_json("A", "B")]})

    _service(tmp_path, llm).plan(_inputs(), api_key=SECRET)

    assert llm.keys_seen == [SECRET]
    assert os.environ["OPENAI_API_KEY"] == "sk-from-env"


@pytest.mark.unit
def test_a_key_with_control_characters_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(service.InputError, match="API key"):
        _service(tmp_path).plan(_inputs(), api_key="sk-abc\nINJECT=1")


@pytest.mark.unit
def test_preview_of_a_course_lists_modules_modes_cost_and_fidelity(tmp_path: Path) -> None:
    llm = _ScriptedLLM(
        {"course_plan": [_plan_json("Arrays", "Hashing", modes=("executable", "conceptual"))]}
    )
    svc = _service(tmp_path, llm)
    inputs = _inputs()
    plan = svc.plan(inputs)

    preview = svc.preview(plan, inputs)

    assert preview.shape == "course"
    assert [(m.number, m.title, m.lesson_mode) for m in preview.modules] == [
        (0, "Arrays", "executable"),
        (1, "Hashing", "conceptual"),
    ]
    assert "Estimated cost" in preview.estimate
    assert preview.fidelity_status in {"covered", "dropped", "not_assessed"}
    assert preview.text.startswith("Proposed plan (2 modules")


@pytest.mark.unit
def test_preview_of_a_single_lesson_says_so(tmp_path: Path) -> None:
    llm = _ScriptedLLM(
        {"course_plan": [_plan_json("Hash maps")], "readiness_verdict": [_REACHABLE]}
    )
    svc = _service(tmp_path, llm)
    inputs = _inputs()

    preview = svc.preview(svc.plan(inputs), inputs)

    assert preview.shape == "lesson"
    assert preview.can_build
    assert any("single lesson" in note for note in preview.notes)


@pytest.mark.unit
def test_preview_blocks_a_course_that_dropped_a_requested_capability(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    inputs = _inputs()
    plan = json.loads(_plan_json("Unrelated A", "Unrelated B"))
    plan_dict = cli_course_dict(plan)

    preview = svc.preview(plan_dict, inputs)

    assert preview.fidelity_status == "dropped"
    assert not preview.can_build
    assert "dropped" in preview.block_reason


@pytest.mark.unit
def test_preview_marks_modules_beyond_max_modules_as_not_built(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    plan = cli_course_dict(json.loads(_plan_json("A", "B", "C")))

    preview = svc.preview(plan, _inputs(), max_modules=1)

    assert [m.built for m in preview.modules] == [True, False, False]
    assert preview.building == 1


@pytest.mark.unit
def test_preview_rejects_a_malformed_plan_with_a_locating_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="module 0"):
        _service(tmp_path).preview({"title": "x", "modules": [{"order": "zero"}]}, _inputs())


def cli_course_dict(planner_json: dict) -> dict:
    """Turn a planner-shaped JSON reply into a course dict via the real planner parser."""
    from forged.curriculum.model import course_to_dict
    from forged.curriculum.planner import CurriculumPlanner

    planner = CurriculumPlanner(personas_dir=cli.DEFAULT_PERSONAS, llm_client=object())
    return course_to_dict(planner._parse_course(json.dumps(planner_json)))


# ── Deterministic edits (no LLM) ────────────────────────────────────────────────────


@pytest.mark.unit
def test_edit_drop_returns_a_new_plan_and_warns_about_lost_capabilities(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    plan = cli_course_dict(json.loads(_plan_json("A", "B", "C")))
    original = json.dumps(plan, sort_keys=True)

    outcome = svc.edit(plan, "drop", (1,))

    assert [m["spec"]["title"] for m in outcome.plan["modules"]] == ["A", "C"]
    assert "Dropped capabilities" in outcome.warning
    assert json.dumps(plan, sort_keys=True) == original  # input never mutated


@pytest.mark.unit
@pytest.mark.parametrize(
    ("op", "targets", "mode", "expected_titles"),
    [
        ("merge", (0, 1), None, 2),
        ("reorder", (2, 0, 1), None, 3),
        ("force_single", (), None, 1),
        ("set_mode", (1,), "artifact", 3),
    ],
)
def test_each_structural_edit_applies_without_an_llm(
    tmp_path: Path, op: str, targets: tuple[int, ...], mode: str | None, expected_titles: int
) -> None:
    llm = _ScriptedLLM({})
    svc = _service(tmp_path, llm)
    plan = cli_course_dict(json.loads(_plan_json("A", "B", "C")))

    outcome = svc.edit(plan, op, targets, mode=mode)

    assert len(outcome.plan["modules"]) == expected_titles
    assert llm.calls == []
    if op == "set_mode":
        assert outcome.plan["modules"][1]["lesson_mode"] == "artifact"
    if op == "reorder":
        assert [m["spec"]["title"] for m in outcome.plan["modules"]] == ["C", "A", "B"]


@pytest.mark.unit
def test_edit_with_a_bad_target_raises_value_error(tmp_path: Path) -> None:
    plan = cli_course_dict(json.loads(_plan_json("A", "B")))

    with pytest.raises(ValueError):
        _service(tmp_path).edit(plan, "merge", (0,))


@pytest.mark.unit
def test_edit_rejects_an_unknown_op(tmp_path: Path) -> None:
    plan = cli_course_dict(json.loads(_plan_json("A", "B")))

    with pytest.raises(ValueError, match="unknown edit"):
        _service(tmp_path).edit(plan, "confirm", ())


@pytest.mark.unit
def test_set_mode_requires_a_valid_mode(tmp_path: Path) -> None:
    plan = cli_course_dict(json.loads(_plan_json("A", "B")))

    with pytest.raises(ValueError, match="mode"):
        _service(tmp_path).edit(plan, "set_mode", (0,), mode="interpretive-dance")


# ── Natural-language adjustments (PlanAdjuster + guided re-plan) ────────────────────


@pytest.mark.unit
def test_adjust_applies_a_classified_structural_op(tmp_path: Path) -> None:
    llm = _ScriptedLLM({"plan_adjustment_intent": [_intent("merge", [0, 1], "merge 0 and 1")]})
    plan = cli_course_dict(json.loads(_plan_json("A", "B", "C")))

    outcome = _service(tmp_path, llm).adjust(plan, "merge 0 and 1", _inputs())

    assert outcome.op == "merge"
    assert len(outcome.plan["modules"]) == 2
    assert not outcome.replanned


@pytest.mark.unit
def test_adjust_escalates_non_structural_feedback_to_a_guided_replan(tmp_path: Path) -> None:
    llm = _ScriptedLLM(
        {
            "plan_adjustment_intent": [_intent("replan", [], "focus on collisions")],
            "course_plan": [_plan_json("Collisions deep dive", "Probing")],
        }
    )
    plan = cli_course_dict(json.loads(_plan_json("A", "B", "C")))

    outcome = _service(tmp_path, llm).adjust(plan, "focus on collisions", _inputs())

    assert outcome.replanned
    assert [m["spec"]["title"] for m in outcome.plan["modules"]] == [
        "Collisions deep dive",
        "Probing",
    ]
    guidance_call = llm.calls[-1][1]
    assert "focus on collisions" in guidance_call


@pytest.mark.unit
@pytest.mark.parametrize(("op", "flag"), [("confirm", "confirmed"), ("cancel", "cancelled")])
def test_adjust_reports_confirm_and_cancel_without_editing(
    tmp_path: Path, op: str, flag: str
) -> None:
    llm = _ScriptedLLM({"plan_adjustment_intent": [_intent(op, [])]})
    plan = cli_course_dict(json.loads(_plan_json("A", "B")))

    outcome = _service(tmp_path, llm).adjust(plan, "yes", _inputs())

    assert getattr(outcome, flag)
    assert outcome.plan == plan


@pytest.mark.unit
def test_adjust_rejects_an_empty_sentence(tmp_path: Path) -> None:
    plan = cli_course_dict(json.loads(_plan_json("A", "B")))

    with pytest.raises(service.InputError):
        _service(tmp_path).adjust(plan, "   ", _inputs())


# ── build → launch ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_build_launches_a_subprocess_with_the_key_only_in_its_environment(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    launcher = _FakeLauncher()
    svc = _service(tmp_path, launcher=launcher)
    plan = cli_course_dict(json.loads(_plan_json("Hash maps")))

    launch = svc.build(plan, _inputs(), api_key=SECRET, options=BuildOptions(provision=False))

    (call,) = launcher.launched
    assert call["env"] == {"OPENAI_API_KEY": SECRET}
    assert SECRET not in " ".join(call["command"])
    assert call["command"][:3] == (sys.executable, "-m", "forged.service")
    assert launch.pid == 4242
    assert launch.run_dir.parent == tmp_path / "runs"
    assert SECRET not in caplog.text
    for path in (tmp_path / "runs").rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_build_writes_a_request_that_round_trips_the_confirmed_plan(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    plan = cli_course_dict(json.loads(_plan_json("Hash maps")))
    inputs = _inputs()

    launch = svc.build(plan, inputs, options=BuildOptions(max_modules=2, provision=False))

    request = service.load_request(launch.request_path)
    assert request.course == course_from_dict(plan)
    assert request.inputs == inputs
    assert request.options == BuildOptions(max_modules=2, provision=False)
    assert launch.run_dir == cli._planned_run_dir(
        request.course, inputs.topic, tmp_path / "runs", request.stamp
    )


@pytest.mark.unit
def test_build_without_a_key_passes_no_key_override(tmp_path: Path) -> None:
    launcher = _FakeLauncher()
    plan = cli_course_dict(json.loads(_plan_json("Hash maps")))

    _service(tmp_path, launcher=launcher).build(plan, _inputs())

    assert launcher.launched[0]["env"] == {}


@pytest.mark.unit
def test_build_refuses_a_course_that_dropped_a_capability(tmp_path: Path) -> None:
    launcher = _FakeLauncher()
    plan = cli_course_dict(json.loads(_plan_json("Unrelated A", "Unrelated B")))

    with pytest.raises(ValueError, match="dropped"):
        _service(tmp_path, launcher=launcher).build(plan, _inputs())
    assert launcher.launched == []


@pytest.mark.unit
def test_status_reports_running_and_exit_codes(tmp_path: Path) -> None:
    class _Exited(_FakeLauncher):
        def poll(self, pid):
            return 1

    plan = cli_course_dict(json.loads(_plan_json("Hash maps")))
    running = _service(tmp_path).build(plan, _inputs())
    svc_exited = _service(tmp_path, launcher=_Exited())
    exited = svc_exited.build(plan, _inputs())

    assert "running" in _service(tmp_path).status(running)
    assert "exited with code 1" in svc_exited.status(exited)


@pytest.mark.unit
def test_dry_run_launcher_records_the_command_and_spawns_nothing(tmp_path: Path) -> None:
    svc = ForgeService(
        personas_dir=cli.DEFAULT_PERSONAS,
        runs_root=tmp_path / "runs",
        launcher=service.DryRunLauncher(),
    )
    plan = cli_course_dict(json.loads(_plan_json("Hash maps")))

    launch = svc.build(plan, _inputs(), api_key=SECRET)

    assert launch.pid is None
    assert "dry run" in svc.status(launch)
    log = launch.log_path.read_text(encoding="utf-8")
    assert "forged.service" in log
    assert SECRET not in log


@pytest.mark.integration
def test_subprocess_launcher_hands_the_key_to_the_child_environment(tmp_path: Path) -> None:
    """A real child process: the key arrives via env and only via env."""
    launcher = service.SubprocessLauncher()
    log_path = tmp_path / "launch.log"
    probe = "import os; print('KEY_OK' if os.environ.get('OPENAI_API_KEY') == %r else 'NO')"

    pid = launcher.launch(
        (sys.executable, "-c", probe % SECRET),
        {"OPENAI_API_KEY": SECRET},
        log_path,
        tmp_path,
    )
    exit_code = launcher.wait(pid, timeout=30)

    assert exit_code == 0
    assert "KEY_OK" in log_path.read_text(encoding="utf-8")
    assert launcher.poll(pid) == 0


@pytest.mark.unit
def test_subprocess_launcher_polls_an_unknown_pid_as_none() -> None:
    assert service.SubprocessLauncher().poll(999_999) is None


# ── The subprocess entry: `python -m forged.service build --request …` ─────────────


@pytest.mark.unit
def test_build_entry_hands_the_request_to_the_cli_build_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = _service(tmp_path)
    plan = cli_course_dict(json.loads(_plan_json("Hash maps")))
    launch = svc.build(plan, _inputs(), options=BuildOptions(max_modules=3, provision=False))
    seen: dict[str, Any] = {}

    def _fake_build(args, course, learner_profile, topic, pipeline, personas_dir, caps, **kw):
        seen.update(args=args, course=course, topic=topic, caps=caps, **kw)
        return 0

    monkeypatch.setattr(cli, "_build_confirmed", _fake_build)

    code = service.main(["build", "--request", str(launch.request_path)])

    assert code == 0
    assert seen["course"] == course_from_dict(plan)
    assert seen["topic"] == "Hash maps"
    assert seen["args"].no_provision is True
    assert seen["args"].max_modules == 3
    assert seen["args"].runs == str(tmp_path / "runs")
    assert seen["stamp"] == service.load_request(launch.request_path).stamp


@pytest.mark.unit
def test_build_entry_on_a_missing_request_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = service.main(["build", "--request", str(tmp_path / "nope.json")])

    assert code == cli.EXIT_USAGE
    assert "nope.json" in capsys.readouterr().err


@pytest.mark.unit
def test_build_entry_refuses_a_request_from_a_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "req.json"
    path.write_text(json.dumps({"version": service.REQUEST_VERSION + 1}), encoding="utf-8")

    assert service.main(["build", "--request", str(path)]) == cli.EXIT_USAGE
