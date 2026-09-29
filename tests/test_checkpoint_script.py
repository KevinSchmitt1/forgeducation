"""Tests for `scripts/checkpoint.py` — the human-in-the-loop checkpoint inbox.

The script is dev tooling (not part of the `forged` package), so it is loaded by path.
Every test points the inbox at a temp file via `LANES_INBOX` and disables the macOS
notification, so nothing touches the real inbox or pops a window.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "checkpoint.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("checkpoint_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["checkpoint_script"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cp(tmp_path, monkeypatch) -> ModuleType:
    monkeypatch.setenv("LANES_INBOX", str(tmp_path / "INBOX.md"))
    monkeypatch.setenv("CHECKPOINT_NO_NOTIFY", "1")
    return _load()


def _inbox(cp: ModuleType) -> str:
    return cp.inbox_path().read_text(encoding="utf-8")


def test_post_appends_an_open_entry_with_summary_and_body(cp):
    cp.main(["post", "--lane", "11", "--cp", "CP0", "--summary", "Plan ready", "--body", "Step 1"])

    text = _inbox(cp)
    assert "⏳ OPEN · Lane 11 · CP0 kickoff" in text
    assert "Plan ready" in text
    assert "Step 1" in text


def test_post_rejects_an_unknown_checkpoint(cp):
    with pytest.raises(SystemExit):
        cp.main(["post", "--lane", "11", "--cp", "CP9", "--summary", "x"])


def test_resolve_marks_only_the_matching_open_entry(cp):
    cp.main(["post", "--lane", "10", "--cp", "CP0", "--summary", "a", "--body", ""])
    cp.main(["post", "--lane", "11", "--cp", "CP0", "--summary", "b", "--body", ""])

    cp.main(["resolve", "--lane", "11", "--cp", "CP0", "--note", "go"])

    text = _inbox(cp)
    assert "⏳ OPEN · Lane 10 · CP0" in text
    assert "⏳ OPEN · Lane 11 · CP0" not in text
    assert "✅ RESOLVED" in text and "go" in text


def test_resolve_without_an_open_entry_fails_loudly(cp):
    assert cp.main(["resolve", "--lane", "11", "--cp", "CP1"]) == 1


def test_list_prints_only_open_entries(cp, capsys):
    cp.main(["post", "--lane", "10", "--cp", "SPEND", "--summary", "replay ~$0.05", "--body", ""])
    cp.main(["post", "--lane", "11", "--cp", "CP2", "--summary", "PR #70", "--body", ""])
    cp.main(["resolve", "--lane", "11", "--cp", "CP2"])
    capsys.readouterr()

    assert cp.main(["list"]) == 0

    out = capsys.readouterr().out
    assert "Lane 10 · SPEND" in out
    assert "Lane 11" not in out


def test_list_with_nothing_waiting_says_so(cp, capsys):
    assert cp.main(["list"]) == 0
    assert "Nothing is waiting" in capsys.readouterr().out
