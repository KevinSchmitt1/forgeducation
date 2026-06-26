"""Per-call LLM token observability.

Every LLM stage funnels through ``LLMClient.complete`` (see ``forged.llm``), so a
single module-level ledger — recorded from inside ``complete`` — captures token
usage for every call across all paths (linear, agentic, curriculum) without
threading anything through the pipeline. It mirrors the ``_TRACER`` singleton in
``forged.llm``: a controlled, thread-safe sink, not pipeline state.

Records are keyed by ``run_id`` so a multi-run process (e.g. a curriculum course
running several lessons) keeps each run's tally separate. After a run finishes,
``write_usage_report`` turns that run's records into ``usage.json`` (machine) and
``USAGE.md`` (human) in the run directory — an offline, provider-agnostic record
of where the tokens went and, crucially, **how much of the input was cached**.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Token kinds tracked per call. Kept as a tuple so report aggregation and the
# JSON/Markdown writers stay in lock-step with one source of truth.
_TOKEN_KINDS = ("input", "cached_input", "output", "reasoning", "total")


@dataclass(frozen=True)
class UsageRecord:
    """Token usage for a single LLM call. Immutable value object."""

    run_id: str
    stage_name: str
    pipeline_kind: str
    provider: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    iteration: int | None = None


class UsageLedger:
    """Thread-safe collector of UsageRecords, partitioned by run_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_run: dict[str, list[UsageRecord]] = {}

    def record(self, record: UsageRecord) -> None:
        with self._lock:
            self._by_run.setdefault(record.run_id, []).append(record)

    def records_for(self, run_id: str) -> tuple[UsageRecord, ...]:
        with self._lock:
            return tuple(self._by_run.get(run_id, ()))

    def clear(self, run_id: str) -> None:
        with self._lock:
            self._by_run.pop(run_id, None)


_LEDGER = UsageLedger()


def record_usage(record: UsageRecord) -> None:
    """Append one call's usage to the module-level ledger."""
    _LEDGER.record(record)


def records_for(run_id: str) -> tuple[UsageRecord, ...]:
    """Return all recorded calls for a run (empty tuple if none)."""
    return _LEDGER.records_for(run_id)


def clear_run(run_id: str) -> None:
    """Drop a run's records — used after writing its report and in tests."""
    _LEDGER.clear(run_id)


def _cached_pct(cached_input: int, input_tokens: int) -> float:
    if input_tokens <= 0:
        return 0.0
    return round(100.0 * cached_input / input_tokens, 1)


def _empty_bucket() -> dict[str, Any]:
    return dict.fromkeys(_TOKEN_KINDS, 0)


def _call_tokens(record: UsageRecord) -> dict[str, int]:
    return {
        "input": record.input_tokens,
        "cached_input": record.cached_input_tokens,
        "output": record.output_tokens,
        "reasoning": record.reasoning_tokens,
        "total": record.total_tokens,
    }


def build_report(
    run_id: str, records: list[UsageRecord] | tuple[UsageRecord, ...]
) -> dict[str, Any]:
    """Aggregate a run's records into a serialisable report.

    Folds calls per stage (preserving first-seen order) and across the whole run.
    Includes the cached-input share of input — the single biggest cost lever for
    this input-dominated pipeline.
    """
    totals = _empty_bucket()
    by_stage: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for record in records:
        call = _call_tokens(record)
        for kind in _TOKEN_KINDS:
            totals[kind] += call[kind]

        stage = by_stage.get(record.stage_name)
        if stage is None:
            stage = {
                "stage": record.stage_name,
                "model": record.model,
                "provider": record.provider,
                "calls": 0,
                **_empty_bucket(),
            }
            by_stage[record.stage_name] = stage
        stage["calls"] += 1
        for kind in _TOKEN_KINDS:
            stage[kind] += call[kind]

    for stage in by_stage.values():
        stage["cached_input_pct"] = _cached_pct(stage["cached_input"], stage["input"])

    totals["cached_input_pct"] = _cached_pct(totals["cached_input"], totals["input"])

    return {
        "run_id": run_id,
        "calls": len(records),
        "totals": totals,
        "by_stage": list(by_stage.values()),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    t = report["totals"]
    lines = [
        f"# Token usage — {report['run_id']}",
        "",
        f"- **Calls:** {report['calls']}",
        f"- **Total tokens:** {t['total']:,}",
        f"- **Input:** {t['input']:,}  (**{t['cached_input_pct']}% cached** — "
        f"{t['cached_input']:,} cached reads)",
        f"- **Output:** {t['output']:,}  (reasoning: {t['reasoning']:,})",
        "",
        "## By stage",
        "",
        "| stage | model | calls | input | cached% | output | reasoning | total |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for stage in report["by_stage"]:
        lines.append(
            f"| {stage['stage']} | {stage['model']} | {stage['calls']} | "
            f"{stage['input']:,} | {stage['cached_input_pct']}% | "
            f"{stage['output']:,} | {stage['reasoning']:,} | {stage['total']:,} |"
        )
    if not report["by_stage"]:
        lines.append("| _(no LLM calls recorded)_ | | | | | | | |")
    lines.append("")
    return "\n".join(lines)


def write_usage_report(run_dir: Path | str, run_id: str) -> Path:
    """Write usage.json + USAGE.md for a run into ``run_dir``.

    Always writes both files, even when no calls were recorded (a zeroed report),
    so the CLI hook produces a predictable artifact every run.
    """
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    report = build_report(run_id, records_for(run_id))

    (run_path / "usage.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (run_path / "USAGE.md").write_text(_render_markdown(report), encoding="utf-8")
    return run_path
