"""A truncated response must not cost a full paid call and return nothing (doc 20, C4).

In the 2026-08-13 run the Reviewer came back with `finish_reason='length'` and empty
content, and the whole call was discarded — that iteration had no expert critic at all.
The cause is that OpenAI counts *reasoning* tokens against `max_completion_tokens`
(`forged/llm.py`), so a 4096 ceiling was consumed by ~2.3K reasoning + output before any
text was emitted.

Raising the config number alone is not the fix: the number is a setting, and the next
model or the next schema moves it again. Truncation is a recoverable condition, so it is
handled as one — retried once with a larger budget.

The retry is exercised through an injected `do_call`, so nothing here constructs a real
client or reaches the network; the repo-wide guard in `tests/conftest.py` stays intact.
"""

from __future__ import annotations

from typing import Any

import pytest

from forged.llm import complete_with_truncation_retry


class _Choice:
    def __init__(self, content: str | None, finish_reason: str) -> None:
        self.message = type("_Msg", (), {"content": content, "refusal": None})()
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content: str | None, finish_reason: str = "stop") -> None:
        self.choices = [_Choice(content, finish_reason)]


class _Recorder:
    """Stands in for the API call; records the budget it was asked for."""

    def __init__(self, *responses: _Response) -> None:
        self._responses = list(responses)
        self.budgets: list[int] = []

    def __call__(self, budget: int) -> Any:
        self.budgets.append(budget)
        return self._responses[min(len(self.budgets) - 1, len(self._responses) - 1)]


@pytest.mark.unit
def test_a_good_response_is_returned_without_a_second_call() -> None:
    call = _Recorder(_Response("the answer"))

    response = complete_with_truncation_retry(call, 4096, model="gpt-5-mini")

    assert response.choices[0].message.content == "the answer"
    assert call.budgets == [4096]


@pytest.mark.unit
def test_an_empty_truncated_response_is_retried_with_a_larger_budget() -> None:
    call = _Recorder(_Response(None, "length"), _Response("recovered"))

    response = complete_with_truncation_retry(call, 4096, model="gpt-5-mini")

    assert response.choices[0].message.content == "recovered"
    assert call.budgets == [4096, 8192], "the retry must actually raise the ceiling"


@pytest.mark.unit
def test_it_retries_at_most_once() -> None:
    """Two truncations means the schema or prompt is wrong, not the ceiling."""
    call = _Recorder(_Response(None, "length"))

    response = complete_with_truncation_retry(call, 4096, model="gpt-5-mini")

    assert response.choices[0].message.content is None
    assert len(call.budgets) == 2


@pytest.mark.unit
def test_a_refusal_is_not_retried() -> None:
    """Empty for a reason other than length is not a budget problem — paying twice
    for the same refusal helps nobody."""
    call = _Recorder(_Response(None, "content_filter"))

    complete_with_truncation_retry(call, 4096, model="gpt-5-mini")

    assert call.budgets == [4096]


@pytest.mark.unit
def test_a_truncated_response_that_still_has_content_is_not_retried() -> None:
    """Partial content is usable — the graders parse leniently. Only a total loss
    is worth a second call."""
    call = _Recorder(_Response('{"quality_score": 8', "length"))

    complete_with_truncation_retry(call, 4096, model="gpt-5-mini")

    assert call.budgets == [4096]


@pytest.mark.unit
def test_a_malformed_response_does_not_crash_the_retry_decision() -> None:
    """Provider differences must degrade, not raise: an Ollama-shaped response with no
    choices should simply be handed back."""

    class _Empty:
        choices: list[Any] = []

    def call(budget: int) -> Any:
        return _Empty()

    assert complete_with_truncation_retry(call, 4096, model="local") is not None
