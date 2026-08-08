"""The repo-wide guard that stops an unmarked test from making a paid LLM call.

On 2026-08-08 two real, unconsented agentic runs (243s and 634s) were billed because a
course test was retargeted from `course` to `learn`: a 1-module plan routes to the
single-lesson branch, which builds real `LLMClient`s. The test failed on its assertion
*after* spending. The same class of bug hit the doc-14 wiring pass.

The guard patches `LLMClient.complete` — the single funnel every billable call goes
through — rather than the constructor, because constructing an `LLMClient` is
deliberately credential-free (see `LLMClient._ensure_client`) and the offline suite
builds real agents everywhere.
"""

from __future__ import annotations

import pytest

from forged.config import ModelConfig
from forged.llm import LLMClient

_REAL_QUALNAME = "LLMClient.complete"


@pytest.mark.unit
def test_unmarked_test_cannot_reach_a_billable_completion() -> None:
    # Arrange — a client is still constructible; only the call is refused.
    client = LLMClient(ModelConfig())

    # Act / Assert
    with pytest.raises(AssertionError, match="live LLM call"):
        client.complete(system_prompt="s", user_prompt="u")


@pytest.mark.unit
def test_guard_is_active_by_default_without_any_opt_in() -> None:
    assert LLMClient.complete.__qualname__ != _REAL_QUALNAME


@pytest.mark.unit
@pytest.mark.live
def test_live_marker_opts_out_so_a_real_run_is_still_possible() -> None:
    # No network here: assert the real method is in place, don't call it.
    assert LLMClient.complete.__qualname__ == _REAL_QUALNAME


@pytest.mark.unit
def test_guard_names_the_stage_it_refused_so_the_failure_is_diagnosable() -> None:
    client = LLMClient(ModelConfig(model="gpt-5"))

    with pytest.raises(AssertionError) as excinfo:
        client.complete(system_prompt="s", user_prompt="u")

    message = str(excinfo.value)
    assert "gpt-5" in message
    assert "pytest.mark.live" in message
