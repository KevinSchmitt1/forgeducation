"""Wiring of the Gradio app and the `forged ui` entry point, plus the small, behaviour-
preserving `cli.py` extractions the service relies on. The browser e2e
(`test_browser_e2e.py`) drives the same app for real."""

from __future__ import annotations

import builtins
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import gradio as gr
import pytest

import forged.cli as cli
from forged.curriculum.model import CourseSpec, ModuleSpec, ReadinessVerdict
from forged.service import DryRunLauncher, SubprocessLauncher
from forged.ui import app as app_mod
from forged.ui.front_door import FrontDoor, Session, View

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _course(*titles: str) -> CourseSpec:
    return CourseSpec(
        title="c",
        modules=tuple(
            ModuleSpec(spec=cli._default_topic_spec(t), order=i) for i, t in enumerate(titles)
        ),
    )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    return subprocess.run(
        [sys.executable, "-m", *args], cwd=_REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=120,
    )


# ── The Gradio app ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_build_app_exposes_every_step_control(tmp_path: Path) -> None:
    door = FrontDoor(app_mod.make_service(tmp_path, fake_llm=True))

    app = app_mod.build_app(door, demo=True)

    elem_ids = {getattr(block, "elem_id", None) for block in app.blocks.values()}
    for wanted in (
        "fd-api-key", "fd-topic", "fd-objectives", "fd-scope", "fd-plan-btn", "fd-plan",
        "fd-edit-op", "fd-edit-btn", "fd-adjust-btn", "fd-confirm-btn", "fd-launch-btn",
        "fd-demo-banner",
    ):
        assert wanted in elem_ids, wanted


@pytest.mark.unit
def test_emit_maps_a_view_onto_button_states() -> None:
    view = View(message="m", plan_markdown="p", has_plan=True, can_launch=True, can_undo=False)

    session, message, plan_md, launch_md, confirm, launch, undo = app_mod._emit(Session(), view)

    assert (message, plan_md, launch_md) == ("m", "p", "")
    assert confirm["interactive"] is True
    assert launch["interactive"] is True
    assert undo["interactive"] is False


@pytest.mark.unit
def test_fake_mode_never_launches_a_real_build(tmp_path: Path) -> None:
    assert isinstance(app_mod.make_service(tmp_path, fake_llm=True).launcher, DryRunLauncher)
    assert isinstance(app_mod.make_service(tmp_path, fake_llm=False).launcher, SubprocessLauncher)


@pytest.mark.integration
def test_the_app_serves_its_page_over_http(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = app_mod.build_app(FrontDoor(app_mod.make_service(tmp_path, fake_llm=True)))
    app.queue().launch(
        server_name="127.0.0.1", server_port=port, prevent_thread_lock=True, quiet=True,
        show_api=False,
    )
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=30) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "forgeducation" in body
    finally:
        app.close()


# ── `forged ui` ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ui_command_passes_its_options_to_serve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(app_mod, "serve", lambda **kw: seen.update(kw))

    code = cli.main(["ui", "--port", "7999", "--runs", str(tmp_path), "--fake-llm"])

    assert code == cli.EXIT_OK
    assert seen == {"host": "127.0.0.1", "port": 7999, "runs": tmp_path, "fake_llm": True}


@pytest.mark.unit
def test_ui_command_rejects_a_bad_port(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["ui", "--port", "0"]) == cli.EXIT_USAGE
    assert "--port" in capsys.readouterr().err


@pytest.mark.unit
def test_ui_command_without_the_extra_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def _no_ui(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ui.app" or name.endswith("forged.ui.app"):
            raise ImportError("No module named 'gradio'", name="gradio")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _no_ui)

    code = cli.main(["ui"])

    assert code == cli.EXIT_USAGE
    assert "pip install 'forged[ui]'" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.parametrize(
    "argv", [("forged.cli", "ui", "--help"), ("forged.ui", "--help")]
)
def test_ui_entry_points_start_the_way_a_user_starts_them(argv: tuple[str, ...]) -> None:
    result = _run(*argv)

    assert result.returncode == 0, result.stderr
    assert "--fake-llm" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.integration
def test_service_build_entry_on_a_missing_request_exits_2_without_traceback(
    tmp_path: Path,
) -> None:
    result = _run("forged.service", "build", "--request", str(tmp_path / "missing.json"))

    assert result.returncode == cli.EXIT_USAGE
    assert "Traceback" not in result.stderr
    assert "missing.json" in result.stderr


@pytest.mark.unit
def test_app_main_delegates_to_the_cli_ui_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 0)

    assert app_mod.main(["--fake-llm"]) == 0
    assert seen == [["ui", "--fake-llm"]]


# ── cli.py extractions (behaviour-preserving) ───────────────────────────────────────


@pytest.mark.unit
def test_planned_run_dir_matches_both_build_shapes(tmp_path: Path) -> None:
    lesson = cli._planned_run_dir(_course("Hash Maps!"), "topic", tmp_path, "20260101-000000")
    course = cli._planned_run_dir(_course("A", "B"), "My Topic", tmp_path, "20260101-000000")

    assert lesson == tmp_path / "20260101-000000_hash_maps"
    assert course == tmp_path / "20260101-000000_course_my_topic"


@pytest.mark.unit
def test_readiness_preflight_uses_an_injected_assessor(tmp_path: Path) -> None:
    class _Assessor:
        def assess(self, **kwargs):
            return ReadinessVerdict(True, "", (), (), "fine")

    course = _course("One")

    result = cli._apply_readiness_preflight(
        course, tmp_path, planner=None, topic="t",
        learner_profile=cli._default_learner_profile(), topic_spec=None,
        assessor=_Assessor(),
    )

    assert result is course


@pytest.mark.unit
def test_build_confirmed_honours_a_pinned_stamp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Path] = {}
    monkeypatch.setattr(cli, "_run_agentic_lesson", lambda **kw: seen.update(kw) or 0)
    args = type("A", (), {"runs": str(tmp_path), "no_provision": True, "debug": False})()

    cli._build_confirmed(args, _course("Solo"), None, "t", None, tmp_path, [], stamp="S")

    assert seen["run_dir"] == tmp_path / "S_solo"


def test_gradio_is_importable_for_the_ui_extra() -> None:
    assert gr.__version__.startswith("5.")
