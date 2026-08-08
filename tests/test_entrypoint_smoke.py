"""Start the CLI the way a user starts it: `python -m forged.cli`.

Every other test in this suite does `import forged.cli`. Users run `-m`, where
`main()` executes at the `__main__` guard — a difference no unit test can see. A
NameError that made the CLI unable to start reached `master` through 700 passing
tests, clean ruff and clean mypy, because nothing in CI had ever *started the
program* (PR #30). This is the mechanical guard for CLAUDE.md norm 1.

Everything here is free: `--help`, `pipelines`, and argument-validation errors
all return before any LLM call. As a second line of defence the subprocess
environment has OPENAI_API_KEY removed, so a regression that reached the network
would fail rather than spend. The in-process conftest guard cannot help here —
these are separate processes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TIMEOUT_SECONDS = 60

# `learn` is the only build command; `pipelines` and `clean` are the utilities.
COMMANDS = ("learn", "pipelines", "clean")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI in a child process with no API key available."""
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    return subprocess.run(
        [sys.executable, "-m", "forged.cli", *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.integration
def test_bare_help_starts_and_exits_clean() -> None:
    result = _run_cli("--help")

    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "learn" in result.stdout


@pytest.mark.integration
@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_has_working_help(command: str) -> None:
    """Catches a subparser wired to a missing handler or a bad default."""
    result = _run_cli(command, "--help")

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.integration
def test_pipelines_runs_without_arguments() -> None:
    """`pipelines` reads bundled config — a real code path, still free."""
    result = _run_cli("pipelines")

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.integration
def test_learn_rejects_a_blank_topic_with_a_usage_error() -> None:
    """A whitespace-only topic must be refused before anything paid begins."""
    result = _run_cli("learn", "--topic", "   ")

    assert result.returncode == 2, f"expected usage exit 2, got {result.returncode}"
    assert "Traceback" not in result.stderr


@pytest.mark.integration
def test_an_unknown_command_is_a_usage_error_not_a_crash() -> None:
    result = _run_cli("definitely-not-a-command")

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
