"""The lane's vertical rung: drive the real app in a real browser (Playwright/Chromium).

Starts the UI the way a user does — `python -m forged.cli ui --fake-llm` in a child
process with no API key in its environment — then fills the form, plans, edits the plan
(structural edits, a mode change, a sentence the adjuster maps to an op, undo, a
guided re-plan), confirms, and launches. The
offline demo LLM answers the planner-side calls and the launch is a dry run, so nothing
reaches the network or spends.

Skipped unless the `e2e` extra and a browser are installed:
    pip install -e '.[e2e]' && python -m playwright install chromium
Set FORGED_E2E_SCREENSHOTS=<dir> to keep the screenshots of each key state.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_KEY = "sk-e2e-not-a-real-key-0000000000"
_BOOT_TIMEOUT_S = 60
_STEP_TIMEOUT_MS = 20_000


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture()
def app_url(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    port = _free_port()
    runs = tmp_path / "runs"
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "forged.cli", "ui", "--fake-llm", "--port", str(port),
         "--runs", str(runs)],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + _BOOT_TIMEOUT_S
    try:
        while True:
            try:
                urllib.request.urlopen(url, timeout=2).close()
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    output = proc.stdout.read().decode() if proc.stdout else ""
                    pytest.fail(f"UI did not start:\n{output}")
                time.sleep(0.5)
        yield url, runs
    finally:
        proc.terminate()
        proc.wait(timeout=15)


@pytest.fixture()
def page(tmp_path: Path) -> Iterator[object]:
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - no browser installed → skip, not fail
            pytest.skip(f"no Playwright browser: {exc}")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        yield context.new_page()
        browser.close()


def _shot(page, name: str, tmp_path: Path) -> None:
    out = Path(os.environ.get("FORGED_E2E_SCREENSHOTS") or tmp_path / "shots")
    out.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out / f"{name}.png"), full_page=True)


def _add_row(page, elem_id: str, text: str) -> None:
    field = page.locator(f"#{elem_id} input")
    field.click()
    field.fill(text)
    field.press("Enter")
    sync_api.expect(page.locator(f"#{elem_id}")).to_contain_text(text)


def _choose(page, elem_id: str, option: str) -> None:
    page.locator(f"#{elem_id} input").click()
    page.get_by_role("option", name=option, exact=True).click()


def _edit(page, op_label: str, targets: str, mode: str | None = None) -> None:
    _choose(page, "fd-edit-op", op_label)
    page.locator("#fd-targets textarea, #fd-targets input").first.fill(targets)
    if mode:
        _choose(page, "fd-mode", mode)
    page.locator("#fd-edit-btn").click()


@pytest.mark.e2e
def test_author_plan_edit_confirm_launch_in_a_real_browser(
    app_url: tuple[str, Path], page, tmp_path: Path
) -> None:
    url, runs = app_url
    expect = sync_api.expect
    expect.set_options(timeout=_STEP_TIMEOUT_MS)
    page.goto(url)
    plan = page.locator("#fd-plan")
    message = page.locator("#fd-message")

    # BYOK field: accepted, masked, and acknowledged without echoing the key.
    page.locator("#fd-api-key input").fill(_FAKE_KEY)
    expect(page.locator("#fd-key-status")).to_contain_text("held in memory only")
    assert page.locator("#fd-api-key input").get_attribute("type") == "password"

    # Validation is shown in the UI, and nothing is planned.
    page.locator("#fd-plan-btn").click()
    expect(message).to_contain_text("topic: must not be empty")
    _shot(page, "01-validation-error", tmp_path)

    # Author inputs without YAML: free text, enum dropdowns, add-a-row lists.
    page.locator("#fd-topic textarea, #fd-topic input").first.fill("Hash maps")
    _choose(page, "fd-depth", "beginner")
    _add_row(page, "fd-objectives", "Build a hash map")
    _add_row(page, "fd-objectives", "Resolve collisions")
    _shot(page, "02-inputs", tmp_path)

    # Plan → the N-module course shape, with modes, cost and fidelity.
    page.locator("#fd-plan-btn").click()
    expect(plan).to_contain_text("a 3-module course")
    expect(plan).to_contain_text("artifact")
    expect(plan).to_contain_text("Estimated cost")
    expect(plan).to_contain_text("every requested capability is covered")
    _shot(page, "03-plan-course", tmp_path)

    # Structural edits (no LLM): drop, then change a module's lesson mode.
    _edit(page, "Drop module(s)", "2")
    expect(plan).to_contain_text("a 2-module course")
    _edit(page, "Set a module's lesson mode", "0", mode="conceptual")
    expect(plan).to_contain_text("conceptual")
    expect(message).to_contain_text("Applied: set mode")

    # A plain-language change the adjuster maps to a structural op → the lesson shape.
    sentence = page.locator("#fd-sentence textarea, #fd-sentence input").first
    sentence.fill("please make it a single lesson")
    page.locator("#fd-adjust-btn").click()
    expect(plan).to_contain_text("a single lesson")
    expect(plan).to_contain_text("checked per lesson")
    expect(message).to_contain_text("Packing every module into one lesson")
    _shot(page, "04-single-lesson", tmp_path)

    # Undo returns to the edited course.
    page.locator("#fd-undo-btn").click()
    expect(plan).to_contain_text("a 2-module course")

    # Non-structural feedback escalates to a guided re-plan (Tier 2).
    sentence.fill("focus more on collision handling")
    page.locator("#fd-adjust-btn").click()
    expect(message).to_contain_text("Re-planned with your guidance")
    expect(plan).to_contain_text("Re-planned for: focus more on collision handling")
    expect(plan).to_contain_text("a 3-module course")
    _shot(page, "05-guided-replan", tmp_path)

    # Confirm unlocks launch.
    expect(page.locator("#fd-launch-btn")).to_be_disabled()
    page.locator("#fd-confirm-btn").click()
    expect(message).to_contain_text("Plan confirmed")
    expect(page.locator("#fd-launch-btn")).to_be_enabled()
    _shot(page, "06-confirmed", tmp_path)

    # Launch (dry run in demo mode): the run dir is shown, Langfuse is pointed at.
    page.locator("#fd-launch-btn").click()
    launch = page.locator("#fd-launch")
    expect(launch).to_contain_text("dry run")
    expect(launch).to_contain_text(str(runs))
    expect(launch).to_contain_text("Langfuse")
    _shot(page, "07-launched", tmp_path)

    # The key never touched the disk or the page text.
    assert _FAKE_KEY not in page.locator("body").inner_text()
    written = [p for p in runs.rglob("*") if p.is_file()]
    assert any(p.name == "ui_request.json" for p in written)
    for path in written:
        assert _FAKE_KEY not in path.read_text(encoding="utf-8")
