# Lane 2 — Local observability (self-hosted Langfuse + trace enrichment)

**Branch:** `feat/local-observability` · **Type:** code · **Depends on:** none
**Process:** see "Parallel lane workflow" in root `CLAUDE.md`.

## Why this lane exists
Langfuse is **already integrated** — `forged/llm.py` creates a real trace per LLM call, seeded with
`run_id` + `pipeline_kind`, recording usage/success/error. The complaint "it has no benefit right now"
is because traces are **call-level, not stitched to pipeline meaning**, and **nobody consumes them**
(no localhost dashboard). Kevin wants observability he can run **on localhost**, no cloud account.
This lane reuses the existing integration instead of replacing it. (`TODO.md` → "Observability
Follow-Up" tracks the earlier instrumentation and its open items — this lane advances that section.)

## Scope (in order)
1. **Self-host Langfuse on localhost** via docker-compose. Wire env (`LANGFUSE_HOST=http://localhost:3000`,
   `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) — `forged/llm.py::_ensure_client` already reads these.
   Add `docker-compose.observability.yml` + `docs/observability.md`. No secrets committed.
2. **Enrich traces with pipeline semantics.** An observation carries provider+model today. Add:
   `stage`, `iteration`, `route_taken`, `quality_score`, the `goal_fit` verdict, `lesson_mode`.
   Thread from where the pipeline already knows them (`agents/__init__.py` builds `LLMTraceContext`;
   `state.py` holds the values). Prefer grouping a run's calls under one trace tree.
3. (Optional, only after 1–2) a bespoke agent-performance view: quality trajectory across iterations,
   route frequency, cost per stage. Also closes `TODO.md`'s open item "surface trace ids in run summaries."

## Files you own (collision map)
- `forged/llm.py` (`_trace_payload`, `_metadata`), `forged/pipeline/agents/__init__.py` (`LLMTraceContext`)
- new: `docker-compose.observability.yml`, `docs/observability.md`
- **Do NOT touch** `router.py`, `failure.py`, `classify()`, `personas/`, `mode.py` (R6/R7 + author-split).
- Note: `forged/llm.py` is also in the SDK-provider lane's scope, but that lane is design-only now.

## Constraints (beyond the shared ones in CLAUDE.md)
- **Observability must never break an LLM call** — keep the best-effort try/except pattern.
- Validate enrichment with **unit tests on the trace-payload builders** — do NOT make a paid run
  (respect `tests/test_live_call_guard.py`). The real localhost view is confirmed on the next paid run.

## Done means
`docker compose -f docker-compose.observability.yml up` gives a Langfuse UI on localhost; unit tests
prove the enriched fields land on the trace payload; docs explain setup. Open a PR.
