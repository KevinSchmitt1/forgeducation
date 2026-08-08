"""Pytest configuration for the forged test suite.

Loads the project .env file (if present) before any test runs, so tests that
exercise the real LLM path can find OPENAI_API_KEY without extra setup.
Keys already present in the environment are never overwritten.

Also installs the repo-wide guard against billable LLM calls — see
`_no_billable_calls` below and `tests/test_live_call_guard.py`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from forged.llm import LLMClient


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no external dependencies required."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# Load .env from project root (the directory containing this tests/ folder)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(_PROJECT_ROOT / ".env")

LIVE_MARKER = "live"


def _refuse(self: LLMClient, *args: Any, **kwargs: Any) -> str:
    """Stand-in for `LLMClient.complete` that spends nothing and says why."""
    model = getattr(getattr(self, "_config", None), "model", "<unknown model>")
    raise AssertionError(
        f"blocked a live LLM call to {model!r}: this test reached "
        "LLMClient.complete, which bills real money. Stub the agent (or the "
        "client) the test exercises. If a real call is genuinely intended, mark "
        "the test with @pytest.mark.live."
    )


@pytest.fixture(autouse=True)
def _no_billable_calls(request: pytest.FixtureRequest) -> Any:
    """Refuse every billable LLM call unless the test is marked `live`.

    `LLMClient.complete` is the single funnel: both `chat.completions.create`
    sites live inside it and every caller in `forged/` goes through it. The
    constructor is deliberately *not* guarded — it is credential-free by design
    so the offline suite can build real agents, and guarding it would break tests
    that never spend anything.

    This exists because a test that forgets to stub does not fail fast; it runs a
    full paid pipeline for minutes and *then* fails on its assertion. Two such
    runs (243s and 634s) were billed on 2026-08-08.
    """
    if request.node.get_closest_marker(LIVE_MARKER) is not None:
        yield
        return
    original = LLMClient.complete
    LLMClient.complete = _refuse  # type: ignore[method-assign]
    try:
        yield
    finally:
        LLMClient.complete = original  # type: ignore[method-assign]
