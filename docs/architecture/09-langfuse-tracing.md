# Langfuse Tracing — Implementation Session

**As of:** 2026-06-14  
**Scope:** Trace every LLM-backed agent prompt through Langfuse for both linear and agentic pipelines  
**Status:** Implemented and validated

---

## Overview

This session added Langfuse tracing at the shared LLM client seam so prompt-level
observability does not depend on which pipeline path is used.

Before this change:

- The repo had LangGraph-based control flow, but no external trace system for
  prompt inspection.
- Stage-specific model configuration existed, but prompt history and per-stage
  model usage were not exported anywhere beyond local logs.
- The only built-in observability surfaces were `SUMMARY.md`, `manifest.json`, and
  `pipeline.log`.

After this change:

- Every real LLM-backed agent call creates a Langfuse generation when
  `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured.
- All generations from one pipeline run are grouped under a stable run-based trace id.
- The tracing layer captures prompt payloads, stage metadata, provider/model, and
  token usage when available from the backend response.
- Tracing remains best-effort: Langfuse failures do not break successful OpenAI or
  Ollama completions.

---

## Goals

1. Capture every LLM-backed prompt without duplicating tracing logic across agents.
2. Keep tracing consistent between the linear and agentic execution paths.
3. Group generations by pipeline run so one lesson build is inspectable as one trace.
4. Avoid turning observability failures into runtime failures for notebook generation.

---

## Implemented Design

### Shared tracing seam

The integration lives in `forged/llm.py`, inside `LLMClient.complete(...)`.

That is the controlling seam because all real LLM-backed calls already funnel through it:

- linear `LLMAgent`
- agentic `PlannerAgent`
- agentic `CodeAuthorAgent`
- agentic `StudentAgent`

This means one tracing implementation captures all prompt traffic automatically.

### Trace context object

`LLMTraceContext` carries the metadata needed to make traces useful:

- `stage_name`
- `pipeline_kind` (`linear` or `agentic`)
- `run_id`
- `run_dir`
- `pipeline_name`
- `iteration`
- `input_artifacts`
- `output_artifact`

Linear and agentic callers now construct this object before calling `complete(...)`.

### Run-level grouping

The Langfuse trace id is derived from a stable seed:

`<pipeline_kind>:<run_id>`

That keeps all generations from a single run together instead of producing unrelated
prompt records.

### Best-effort behavior

The Langfuse client is initialized lazily and only when credentials are present.

If tracing is unavailable because:

- the SDK is missing
- credentials are absent
- Langfuse initialization fails
- observation updates fail

the LLM call still succeeds normally. Tracing is additive, not required.

---

## What Langfuse Captures

Each generation records:

- the full OpenAI-style message list (`system` + `user`)
- resolved `provider`
- resolved `model`
- stage name
- pipeline kind
- run id
- run directory
- iteration when available
- input artifact names
- output artifact name
- model parameters (`temperature`, `max_tokens`)
- token usage details when present in the response

This gives you per-agent prompt inspection without adding tracing logic to every
individual agent implementation.

---

## Files Changed

### Core implementation

- `forged/llm.py`
  - added `LLMTraceContext`
  - added lazy Langfuse client initialization
  - added generation creation/update/end logic
  - made tracing best-effort so failures do not affect completions

- `forged/agent.py`
  - linear `LLMAgent` now passes trace context into `LLMClient.complete(...)`

- `forged/pipeline/agents/__init__.py`
  - added shared `_complete_llm(...)` helper for agentic agents

- `forged/pipeline/agents/planner.py`
- `forged/pipeline/agents/code_author.py`
- `forged/pipeline/agents/student.py`
  - now pass run/stage/artifact metadata into the shared tracing seam

### Runtime configuration

- `pyproject.toml`
  - added `langfuse` runtime dependency

- `.env.example`
  - documented `LANGFUSE_PUBLIC_KEY`
  - documented `LANGFUSE_SECRET_KEY`
  - documented optional host configuration

### Tests

- `tests/test_pipeline.py`
  - added focused tracing behavior tests at the shared client seam

- `tests/pipeline/test_agents_concrete.py`
- `tests/pipeline/test_real_pipeline_integration.py`
  - updated minimal stub clients to accept the new optional trace argument

---

## Validation

Focused validation executed after implementation:

```bash
python -m pytest -q tests/test_pipeline.py tests/pipeline/test_agents_llm.py tests/pipeline/test_agents_concrete.py tests/pipeline/test_real_pipeline_integration.py
python -m pytest -q tests/pipeline/test_graph_integration.py tests/test_cli_agentic.py
```

Result:

- `157 passed`

Code review outcome:

- one regression risk was found and fixed during the session: Langfuse update/init
  failures now degrade gracefully instead of breaking successful completions

---

## Known Caveat

Installing `langfuse` in the active environment emitted unrelated OpenTelemetry
dependency warnings. The forged test suite still passed after installation, so the
repo-level behavior is currently acceptable, but the Python environment is not a
fully clean observability sandbox.

This is an environment hygiene concern, not a forged tracing correctness bug.

---

## What This Enables Next

With prompt-level tracing in place, the next useful observability steps are:

1. surface the Langfuse trace id or trace URL in `SUMMARY.md` and/or `manifest.json`
2. compare notebook quality and cost across model mixes using the existing
   stage-specific model configuration
3. attach more non-LLM run metadata when needed, such as routing summaries or gate results

Related docs kept in sync with this session:

- `TODO.md` — roadmap now treats trace linking and model comparison as the next work
- `DEVELOPMENT.md` — contributor guide now points to this file for tracing details
- `07-agentic-pipeline-status.md` — current-status doc now includes tracing as implemented capability
- `08-stage-specific-models.md` — model-config note now points here for the observability follow-up

---

## Summary

This session moved the repo from local-only prompt observability to external run-level
tracing through Langfuse.

The key architectural outcome is that tracing is now attached to the shared LLM seam,
not to individual agents, which keeps the implementation small and ensures both the
linear and agentic paths stay aligned.