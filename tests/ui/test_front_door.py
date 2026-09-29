"""The UI controller (`forged.ui.front_door`): every button's behaviour as a pure
function of (session, widget values) → (new session, view). Gradio-free, so the whole
plan → edit → confirm → launch round-trip is tested without a browser; the browser e2e
proves the wiring on top."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

import forged.cli as cli
from forged.service import DryRunLauncher, ForgeService
from forged.ui.fake_llm import FakeLLM
from forged.ui.front_door import FormValues, FrontDoor, Session, redact

SECRET = "sk-test-SECRET-front-door-0987654321"


class _RecordingLauncher:
    def __init__(self) -> None:
        self.env: dict[str, str] | None = None

    def launch(self, command, env_overrides, log_path, cwd):
        self.env = dict(env_overrides)
        return 777

    def poll(self, pid):
        return None


class _BrokenLLM:
    def complete(self, *args, **kwargs):
        raise RuntimeError(f"LLM call failed: Incorrect API key provided: {SECRET}")


def _door(tmp_path: Path, launcher=None, llm=None) -> FrontDoor:
    return FrontDoor(
        ForgeService(
            personas_dir=cli.DEFAULT_PERSONAS,
            runs_root=tmp_path / "runs",
            llm_factory=lambda _m: llm or FakeLLM(),
            launcher=launcher or DryRunLauncher(),
        )
    )


def _form(**overrides) -> FormValues:
    base = FormValues.defaults("Hash maps")
    return FormValues(**{**base.__dict__, **overrides})


def _planned(door: FrontDoor) -> Session:
    session, view = door.plan(Session(), "", _form())
    assert view.has_plan, view.message
    return session


@pytest.mark.unit
def test_defaults_prefill_the_cli_defaults() -> None:
    form = FormValues.defaults("Graphs")

    inputs = form.to_inputs()

    assert inputs.learner_profile == cli._default_learner_profile()
    assert inputs.topic_spec == cli._default_topic_spec("Graphs")


@pytest.mark.unit
def test_plan_shows_the_course_with_modes_cost_and_fidelity(tmp_path: Path) -> None:
    session, view = _door(tmp_path).plan(Session(), "", _form())

    assert view.has_plan and not view.confirmed and not view.can_launch
    assert "[0]" in view.plan_markdown and "[2]" in view.plan_markdown
    assert "artifact" in view.plan_markdown and "conceptual" in view.plan_markdown
    assert "Estimated cost" in view.plan_markdown
    assert "Fidelity" in view.plan_markdown
    assert session.inputs is not None


@pytest.mark.unit
def test_invalid_inputs_are_listed_in_the_ui_and_nothing_is_planned(tmp_path: Path) -> None:
    session, view = _door(tmp_path).plan(Session(), "", _form(topic=" ", scope="everything"))

    assert not view.has_plan
    assert "topic" in view.message and "everything" in view.message
    assert session == Session()


@pytest.mark.unit
def test_planner_failures_are_shown_redacted(tmp_path: Path) -> None:
    _, view = _door(tmp_path, llm=_BrokenLLM()).plan(Session(), SECRET, _form())

    assert "Planning failed" in view.message
    assert SECRET not in view.message


@pytest.mark.unit
def test_structural_edit_updates_the_plan_and_enables_undo(tmp_path: Path) -> None:
    door = _door(tmp_path)
    session = _planned(door)

    edited, view = door.edit(session, "drop", "1", None)

    assert len(edited.plan["modules"]) == 2
    assert view.can_undo
    assert "Dropped capabilities" in view.message
    undone, _ = door.undo(edited)
    assert undone.plan == session.plan


@pytest.mark.unit
@pytest.mark.parametrize("targets", ["x", "1,,", "-1"])
def test_bad_target_text_is_reported_not_raised(tmp_path: Path, targets: str) -> None:
    door = _door(tmp_path)
    session = _planned(door)

    after, view = door.edit(session, "drop", targets, None)

    assert after == session
    assert "module numbers" in view.message or "Could not apply" in view.message


@pytest.mark.unit
def test_out_of_range_target_is_reported(tmp_path: Path) -> None:
    door = _door(tmp_path)
    session = _planned(door)

    after, view = door.edit(session, "merge", "0, 9", None)

    assert after == session
    assert "Could not apply" in view.message


@pytest.mark.unit
def test_set_mode_edit(tmp_path: Path) -> None:
    door = _door(tmp_path)

    edited, _ = door.edit(_planned(door), "set_mode", "0", "conceptual")

    assert edited.plan["modules"][0]["lesson_mode"] == "conceptual"


@pytest.mark.unit
def test_adjuster_replan_to_a_single_lesson_shows_the_lesson_shape(tmp_path: Path) -> None:
    door = _door(tmp_path)

    session, view = door.adjust(_planned(door), "", "please make it a single lesson")

    assert len(session.plan["modules"]) == 1
    assert "single lesson" in view.plan_markdown.lower()


@pytest.mark.unit
def test_adjuster_confirm_and_cancel(tmp_path: Path) -> None:
    door = _door(tmp_path)
    session = _planned(door)

    confirmed, view = door.adjust(session, "", "yes")
    cancelled, cancel_view = door.adjust(session, "", "cancel")

    assert confirmed.confirmed and view.can_launch
    assert cancelled.plan is None and "nothing was run" in cancel_view.message.lower()


@pytest.mark.unit
def test_any_edit_after_confirm_requires_confirming_again(tmp_path: Path) -> None:
    door = _door(tmp_path)
    confirmed, _ = door.confirm(_planned(door))

    edited, view = door.edit(confirmed, "merge", "0 1", None)

    assert not edited.confirmed and not view.can_launch


@pytest.mark.unit
def test_launch_before_confirm_is_refused(tmp_path: Path) -> None:
    door = _door(tmp_path)

    session, view = door.launch(_planned(door), "")

    assert session.launch is None
    assert "Confirm the plan" in view.message


@pytest.mark.unit
def test_launch_hands_the_key_to_the_build_env_and_never_shows_or_logs_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    launcher = _RecordingLauncher()
    door = _door(tmp_path, launcher=launcher)
    confirmed, _ = door.confirm(_planned(door))

    session, view = door.launch(confirmed, SECRET)

    assert launcher.env == {"OPENAI_API_KEY": SECRET}
    assert session.launch is not None and session.launch.pid == 777
    assert str(session.launch.run_dir) in view.launch_markdown
    assert "Langfuse" in view.launch_markdown
    assert SECRET not in view.launch_markdown + view.message + caplog.text
    assert SECRET not in repr(session)
    for path in (tmp_path / "runs").rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8")


@pytest.mark.unit
def test_dry_run_launch_and_status(tmp_path: Path) -> None:
    door = _door(tmp_path)
    confirmed, _ = door.confirm(_planned(door))

    launched, view = door.launch(confirmed, "")
    _, status_view = door.status(launched)

    assert "dry run" in view.launch_markdown
    assert "dry run" in status_view.launch_markdown


@pytest.mark.unit
def test_max_modules_option_caps_the_preview(tmp_path: Path) -> None:
    door = _door(tmp_path)

    session, view = door.set_options(_planned(door), 1, True)

    assert session.options.max_modules == 1
    assert "NOT BUILT" in view.plan_markdown


@pytest.mark.unit
@pytest.mark.parametrize("cleared", [None, 0])
def test_blank_or_zero_max_modules_means_build_everything(tmp_path: Path, cleared) -> None:
    door = _door(tmp_path)

    session, view = door.set_options(_planned(door), cleared, False)

    assert session.options.max_modules is None and not session.options.provision
    assert "NOT BUILT" not in view.plan_markdown
    assert not view.message


@pytest.mark.unit
def test_invalid_max_modules_is_reported(tmp_path: Path) -> None:
    door = _door(tmp_path)
    session = _planned(door)

    after, view = door.set_options(session, -3, True)

    assert after.options == session.options
    assert "max modules" in view.message.lower()


@pytest.mark.unit
def test_confirm_without_a_plan_explains_itself(tmp_path: Path) -> None:
    session, view = _door(tmp_path).confirm(Session())

    assert not session.confirmed
    assert "Plan" in view.message


@pytest.mark.unit
def test_key_status_mentions_the_environment_without_revealing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)

    text = FrontDoor.key_status("")

    assert "environment" in text
    assert SECRET not in text
    assert os.environ["OPENAI_API_KEY"] == SECRET


@pytest.mark.unit
def test_redact_masks_the_key_and_key_shaped_tokens() -> None:
    text = f"bad key {SECRET} and sk-proj-abcdEFGH1234****wxyz here"

    cleaned = redact(text, SECRET)

    assert SECRET not in cleaned
    assert "sk-proj-abcd" not in cleaned
    assert "[redacted]" in cleaned
