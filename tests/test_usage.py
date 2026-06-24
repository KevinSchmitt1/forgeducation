"""Tests for per-call LLM token observability (forged.usage).

The ledger collects one UsageRecord per LLM call (recorded inside
LLMClient.complete), keyed by run_id so a multi-run process stays separated.
write_usage_report turns a run's records into usage.json (machine) + USAGE.md
(human) so every run carries its own input/output/cached-token breakdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from forged.usage import (
    UsageRecord,
    build_report,
    clear_run,
    record_usage,
    records_for,
    write_usage_report,
)


def _record(run_id: str, stage: str, model: str, *, inp: int, cached: int, out: int,
            reasoning: int = 0, iteration: int | None = 0) -> UsageRecord:
    return UsageRecord(
        run_id=run_id,
        stage_name=stage,
        pipeline_kind="agentic",
        provider="openai",
        model=model,
        input_tokens=inp,
        cached_input_tokens=cached,
        output_tokens=out,
        reasoning_tokens=reasoning,
        total_tokens=inp + out,
        iteration=iteration,
    )


@pytest.mark.unit
def test_ledger_isolates_runs() -> None:
    """Records under different run_ids never bleed into each other's report."""
    # Arrange
    clear_run("run-A")
    clear_run("run-B")
    record_usage(_record("run-A", "planner", "gpt-5-mini", inp=100, cached=0, out=10))
    record_usage(_record("run-B", "planner", "gpt-5-mini", inp=999, cached=0, out=99))

    # Act
    a = records_for("run-A")
    b = records_for("run-B")

    # Assert
    assert len(a) == 1 and a[0].input_tokens == 100
    assert len(b) == 1 and b[0].input_tokens == 999
    clear_run("run-A")
    clear_run("run-B")


@pytest.mark.unit
def test_report_aggregates_by_stage_and_totals() -> None:
    """build_report sums per stage and across the whole run."""
    # Arrange — two code_author calls + one planner call
    records = [
        _record("r", "planner", "gpt-5-mini", inp=200, cached=0, out=20),
        _record("r", "code_author", "gpt-5", inp=1000, cached=400, out=300, reasoning=120),
        _record("r", "code_author", "gpt-5", inp=1200, cached=900, out=350, reasoning=140),
    ]

    # Act
    report = build_report("r", records)

    # Assert — run totals
    assert report["calls"] == 3
    assert report["totals"]["input"] == 2400
    assert report["totals"]["cached_input"] == 1300
    assert report["totals"]["output"] == 670
    assert report["totals"]["reasoning"] == 260
    assert report["totals"]["total"] == 2400 + 670

    # Assert — code_author stage folded across its two calls
    ca = next(s for s in report["by_stage"] if s["stage"] == "code_author")
    assert ca["calls"] == 2
    assert ca["input"] == 2200
    assert ca["cached_input"] == 1300
    assert ca["output"] == 650
    assert ca["model"] == "gpt-5"


@pytest.mark.unit
def test_report_computes_cached_input_percentage() -> None:
    """The cached-input share of input is reported (the caching lever)."""
    records = [_record("r", "code_author", "gpt-5", inp=1000, cached=750, out=100)]
    report = build_report("r", records)
    assert report["totals"]["cached_input_pct"] == pytest.approx(75.0)


@pytest.mark.unit
def test_report_empty_run_is_zeroed_not_crashing() -> None:
    """A run with no recorded calls yields a zeroed report (no div-by-zero)."""
    report = build_report("empty", [])
    assert report["calls"] == 0
    assert report["totals"]["input"] == 0
    assert report["totals"]["cached_input_pct"] == 0.0
    assert report["by_stage"] == []


@pytest.mark.unit
def test_write_usage_report_writes_json_and_md(tmp_path: Path) -> None:
    """write_usage_report emits usage.json + USAGE.md from the ledger."""
    # Arrange
    clear_run("run-W")
    record_usage(
        _record("run-W", "code_author", "gpt-5", inp=1000, cached=400, out=300, reasoning=120)
    )

    # Act
    write_usage_report(tmp_path, "run-W")

    # Assert
    usage_json = tmp_path / "usage.json"
    usage_md = tmp_path / "USAGE.md"
    assert usage_json.is_file() and usage_md.is_file()
    data = json.loads(usage_json.read_text(encoding="utf-8"))
    assert data["run_id"] == "run-W"
    assert data["totals"]["input"] == 1000
    md = usage_md.read_text(encoding="utf-8")
    assert "code_author" in md and "gpt-5" in md
    clear_run("run-W")


@pytest.mark.unit
def test_write_usage_report_handles_empty_run(tmp_path: Path) -> None:
    """The CLI hook always emits a report even when no LLM calls were recorded."""
    clear_run("none")
    write_usage_report(tmp_path, "none")
    assert (tmp_path / "usage.json").is_file()
    assert (tmp_path / "USAGE.md").is_file()


@pytest.mark.unit
def test_usage_details_extracts_cached_and_reasoning() -> None:
    """_usage_details surfaces cached-input and reasoning tokens when present."""
    from forged.llm import _usage_details

    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=300,
            total_tokens=1300,
            prompt_tokens_details=SimpleNamespace(cached_tokens=400),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=120),
        )
    )
    details = _usage_details(response)
    assert details is not None
    assert details["input"] == 1000
    assert details["output"] == 300
    assert details["cached_input"] == 400
    assert details["reasoning"] == 120


@pytest.mark.unit
def test_usage_details_is_none_safe_without_details() -> None:
    """Providers without cached/reasoning detail blocks (e.g. Ollama) don't crash."""
    from forged.llm import _usage_details

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5, total_tokens=55)
    )
    details = _usage_details(response)
    assert details is not None
    assert details["input"] == 50
    assert "cached_input" not in details  # absent rather than fabricated
