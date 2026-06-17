# Agentic Pipeline — Implementation Status

**As of:** 2026-06-14  
**Phases complete:** 1–9 (state → routing → agents → LangGraph → reviser feedback → CLI)  
**Last full-suite benchmark:** 292 tests passing, 89% overall coverage (2026-06-09)  
**Focused follow-up validation:** 99 targeted tests passing for stage-specific model configuration and 157 targeted tests passing for Langfuse tracing follow-up (2026-06-14)  
**Status:** Production-ready for personal testing

---

## What the Agentic Pipeline Is

The agentic pipeline is a LangGraph-based multi-stage workflow that routes a lesson between
specialised agents deterministically. Unlike the linear pipeline — which runs a fixed
sequence — the agentic pipeline classifies failures, decides which agent can fix them, and
routes back to that agent with the failure context attached.

**Why it exists:**

The linear pipeline runs every stage once in sequence. If the executor finds a failing cell
or the student finds a content gap, the run either retries blindly or stops. The agentic
pipeline replaces that with:

1. A deterministic classifier that maps concrete signals to six failure categories.
2. A budget-aware router that prevents infinite loops.
3. Auditable `RoutingDecision` entries so every reroute is traceable in `state.routing_log`.

This is the foundation for the curriculum planner (Phase 2) and for step-7 comparative
testing (linear vs. agentic quality).

---

## Implementation Summary

### Phase 1 — State Schema (`forged/pipeline/state.py`)

Defines the immutable `PipelineState` dataclass and all supporting types:
`PipelineStage`, `LocationType`, `Location`, `Evidence`, `RoutingDecision`, `StageOutput`.

All builder methods (`with_current_stage`, `with_output`, `with_routing_decision`,
`with_attempt`, `with_terminal`) return new instances via `dataclasses.replace()` — never
mutate in place. `create_initial_state()` is the only public factory.

Coverage: 100%. Tests: `tests/pipeline/test_state.py`.

### Phase 2 — Failure Classification (`forged/pipeline/failure.py`)

Implements `classify(execution_report, grade_report) -> Classification`.

Six categories in priority order:
- `BLOCKER_STRUCTURE` — a BLOCKER finding scoped to lesson structure → reroute to Planner
- `CODE_QUALITY` — execution failed (notebook did not run) → reroute to CodeAuthor
- `TEST_FAILURE` — code runs but a HIGH severity code finding exists → reroute to CodeAuthor
- `CONTENT_QUALITY` — quality score below threshold (default 80.0) → reroute to Reviser
- `ACCEPTABLE` — execution OK, quality at or above threshold → terminate (success)
- `UNCLASSIFIABLE` — no signals available → terminate (human review needed)

Classification is fully deterministic: no LLM calls, no randomness.
Coverage: 100%. Tests: `tests/pipeline/test_failure.py`.

### Phase 3 — Routing & Budget (`forged/pipeline/router.py`)

Implements `Router.route(request) -> RoutingResult`.

Default `RoutingBudget`: Planner ×2, CodeAuthor ×3, Student ×1, Reviser ×1, Executor
unlimited. When a stage's budget is exhausted, the router terminates the pipeline with
`reason="budget exhausted for <stage>"` rather than looping.

Each non-terminal routing decision produces a `RoutingDecision` with timestamp, evidence
list, classification, and `to_stage`.

Coverage: 100%. Tests: `tests/pipeline/test_router.py`.

### Phase 4 — Agent Protocol (`forged/pipeline/agents/__init__.py`)

Defines the `Agent[T]` abstract base class. Persona files are loaded at `__init__` time —
construction fails immediately with `FileNotFoundError` if the file is missing, so broken
deploys surface at startup rather than mid-run.

All concrete agents implement `_load_persona() -> str`, `next_stage()`, and
`async run(state, store) -> PipelineState`.

Coverage: 100%. Tests: `tests/pipeline/test_agents.py`.

### Phase 5 — Concrete Agents

| Agent | File | LLM | Persona file |
|---|---|---|---|
| PlannerAgent | `agents/planner.py` | Yes | `personas/planner.md` |
| CodeAuthorAgent | `agents/code_author.py` | Yes | `personas/code_author.md` |
| ExecutorAgent | `agents/executor.py` | No (real notebook execution) | none |
| StudentAgent | `agents/student.py` | Yes | `personas/student.md` |
| RevisorAgent | `agents/reviser.py` | No (deterministic) | `personas/reviser.md` |

Agents with LLM calls degrade gracefully on errors: they log the failure and return a
terminal state rather than raising. CodeAuthor strips ` ```json ` fences and validates that
the response is a JSON array before writing a notebook artifact. Student parses a structured
grade report JSON and falls back to a zero-score report on parse failure.

`RevisorAgent` calls `classify()` and `Router.route()` with no LLM — routing is purely
deterministic. Its `_coerce_location_type()` method accepts loose labels from real LLM
output (e.g., `"notebook"` → `LocationType.ARTIFACT`) to avoid crashing on valid feedback.

Coverage: 92–96% per agent. Tests: `tests/pipeline/test_agents_concrete.py`,
`tests/pipeline/test_agents_llm.py`.

### Phase 6 — LangGraph Assembly (`forged/pipeline/graph.py`)

`build_pipeline_graph(store, pipeline, personas_dir)` wires five nodes into a `StateGraph`:

```
START → planner → code_author → executor → student → revisor
                     ↑               ↑                   │
                     └───────────────┴───── conditional ──┘
                                              (or END)
```

The conditional edge function `revisor_route(state)` reads `state.routing_log[-1].to_stage`
to determine the next node name, or returns `END` if the state is terminal or the log is
empty.

`run_pipeline(initial_state, store, pipeline, personas_dir)` is the public entry point. It calls
`graph.ainvoke(initial_state)` and reconstructs a typed `PipelineState` from the returned
dict.

Coverage: 96%. Tests: `tests/pipeline/test_graph_integration.py` (20 tests covering graph
compilation, node membership, conditional routing, full pipeline runs, budget exhaustion,
and error handling).

---

## Real-World Validation

Both execution paths were tested end-to-end with a valid `OPENAI_API_KEY`:

**Linear pipeline (`forged build`):** runs the full plan → code_author → executor →
student → reviser sequence, produces `lesson.ipynb` with real cell outputs, and writes
`SUMMARY.md` with the acceptance verdict.

**Agentic pipeline (`run_pipeline`):** the gate parser (`forged/gate.py`) had a bug where
a `94/100` verdict string was not parsed correctly. That was fixed. The pipeline ran
end-to-end, classified the result as `ACCEPTABLE`, and terminated cleanly. The routing log
had one entry; `state.is_terminal` was `True`.

---

## Current Capabilities

- Deterministic failure classification across 6 categories with auditable matched signals.
- Budget-aware routing that prevents infinite loops without relying on LLM judgment.
- Three LLM agents (Planner, CodeAuthor, Student) with graceful degradation on
  error; Reviser (deterministic routing) and Executor (real notebook execution)
  use no LLM.
- Shared stage-specific model configuration across both linear and agentic paths.
- Agentic `--config` support so model selection comes from pipeline YAML rather than
  an implicit per-agent default.
- Optional Langfuse tracing for every LLM-backed prompt, grouped by pipeline run.
- Full LangGraph graph that compiles, runs, and routes correctly.
- Complete immutable state trail: every routing decision is recorded in
  `state.routing_log` with classification, evidence, and timestamp.
- Last known full-suite benchmark: 292 tests passing, 89% overall coverage.

### 2026-06-14 Update — Stage-Specific Models

Stage-specific model defaults are now implemented for both execution paths.

What changed:

- `PipelineConfig` now resolves models through shared defaults plus a logical
  `stage_models` mapping.
- The agentic CLI loads pipeline config via `--config` and passes it into graph
  construction.
- Planner, CodeAuthor, and Student receive stage-specific `LLMClient` instances
  during graph assembly.
- The linear revision-loop reviser now resolves its own configured model explicitly.

Bundled defaults are documented in:

- `docs/architecture/08-stage-specific-models.md`

### 2026-06-14 Update — Langfuse Tracing

Langfuse tracing is now integrated at the shared LLM client layer.

What changed:

- `forged/llm.py` now creates one Langfuse generation per LLM call when
  `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured.
- Linear and agentic paths both pass stage/run metadata into the tracing layer.
- Generations are grouped by stable run-based trace id rather than emitted as
  unrelated single calls.
- Tracing is best-effort: Langfuse failures do not break successful OpenAI or
  Ollama calls.

Implementation details are documented in:

- `docs/architecture/09-langfuse-tracing.md`

---

## Known Limitations

✅ **All Phase 7-9 limitations resolved:**
- ✅ Real executor integrated (Phase 7) — detects notebook failures
- ✅ Revision brief feedback added (Phase 8) — agents iterate intelligently
- ✅ CLI command implemented (Phase 9) — `forged agentic --brief "..." --run-dir /path`

### Budget exhaustion behavior

When a stage hits its budget, the pipeline terminates with `is_terminal=True`,
`terminal_ok=False`, and `terminal_reason="budget exhausted for <stage>"`. The notebook is
still written to `lesson.ipynb` (latest executed or assembled notebook), but the CLI exits
non-zero — budget exhaustion is a safety valve, and the output needs human review before use.

### ~~Content-quality routing is a no-op~~ — RESOLVED (2026-06-17, output-quality Phase 4)

`CONTENT_QUALITY` now routes to a real LLM-backed **ContentReviserAgent**
(`agents/content_reviser.py`) that rewrites the notebook from the reviser's findings; the
rewrite is re-executed and re-graded. The deterministic `RevisorAgent` keeps owning routing.
See `docs/architecture/10-output-quality-remediation.md` (Phase 4).

### 2026-06-17 Update — Output-Quality Remediation (Phases 1–6)

A six-phase remediation hardened the pipeline against the failure mode where a notebook
executed "green" while teaching nothing (the localLLM run). Fully documented in
`docs/architecture/10-output-quality-remediation.md`; summary of what changed here:

- **Honest signals (P1–P2):** a failed student grade is its own signal (never a neutral
  score); rubric-dimensioned grades; silent fallbacks recorded as `degradations` and shown
  in SUMMARY.md; new deterministic anti-hollow gate `forged/pipeline/structure.py` refuses
  an executed-but-hollow notebook at the ACCEPTABLE gate.
- **Self-contained deliverable (P3/P6):** `forged/pipeline/dependencies.py` extracts the
  plan's requirements (+ a stable hash); `forged/packaging.py` writes a learner `README.md`
  + `requirements.txt` into every run dir.
- **Real content reviser (P1/D2):** `agents/content_reviser.py` is now the `CONTENT_QUALITY`
  target (see resolved limitation above).
- **Default provisioning (P0/D1):** `forged/provisioning.py` builds/reuses a content-addressed
  per-run venv from the requirements (allow-list + install timeout + size cap, subprocess
  argv-only), registers a kernel, and runs the notebook against it; a provisioning failure
  terminates honestly. On by default in `forged agentic`; `--no-provision` opts out.
  Validated by a real run on the original localLLM topic — the lesson now runs 7/7 cells
  non-hollow (vs the original all-skipped green notebook).

New agent in the Phase-5 table: **ContentReviserAgent** (`agents/content_reviser.py`, LLM,
`personas/reviser.md`).

---

## Phase Completion Status

### ✅ Phase 7 — Wire the Real Executor (Complete)

**Done:** `ExecutorAgent._execute_real()` calls `forged.executor.ExecutorStage`.

Changes made:
- `forged/pipeline/agents/executor.py`: Integrated real executor with error extraction
- Detects execution failures (failed cells, error summaries)
- Returns ExecutionReport format for classification
- Tests: `test_executor_agent_detects_failing_notebook()`, `test_real_executor_detects_code_quality_failure()`

### ✅ Phase 8 — Add Reviser Rewriting (Complete)

**Done:** RevisorAgent writes `revision_brief_v{N}.md` with structured feedback.

Changes made:
- `forged/pipeline/agents/reviser.py`: Synthesizes revision brief with failure context
- `forged/pipeline/agents/code_author.py`: Reads revision brief, includes in LLM prompt
- `forged/pipeline/agents/planner.py`: Reads revision brief when rerouted
- Result: Agents iterate intelligently based on specific failures
- Test: `test_reviser_writes_revision_brief()`

### ✅ Phase 9 — Expose via CLI (Complete)

**Done:** `forged agentic --brief "..." --run-dir /path` command available.

Changes made:
- `forged/cli.py`: Added agentic subcommand with arg parsing
- `forged/cli.py`: Implemented `_cmd_agentic()` that invokes `run_pipeline()`
- `forged/logging_config.py`: Centralized logging setup
- Output: lesson.ipynb, SUMMARY.md with routing log, pipeline.log with trace
- Tests: `test_agentic_cli_runs_pipeline()`, `test_agentic_cli_writes_summary_with_routing_log()`

### ✅ 2026-06-14 Follow-Up — Stage-Specific Models (Complete)

**Done:** both execution paths now share explicit model-resolution logic.

Changes made:

- `forged/config.py`: added `stage_models` and logical-stage model resolution
- `forged/cli.py`: agentic path now accepts/loads `--config`
- `forged/pipeline/graph.py`: graph construction injects stage-specific LLM clients
- `forged/orchestrator.py`: linear reviser resolves `reviser` explicitly
- `config/pipeline.*.yaml`: bundled mixed-model defaults added

Focused validation:

- `python -m pytest -q tests/test_pipeline.py tests/test_cli_agentic.py tests/pipeline/test_graph_integration.py`
- Result: `99 passed`

### ✅ 2026-06-14 Follow-Up — Langfuse Tracing (Complete)

**Done:** every real LLM-backed agent prompt is now traced through the shared client seam.

Changes made:

- `forged/llm.py`: added lazy, env-driven Langfuse generation tracing
- `forged/agent.py`: linear LLMAgent passes run/stage trace context
- `forged/pipeline/agents/*.py`: Planner, CodeAuthor, and Student pass agentic trace context
- `.env.example` / `pyproject.toml`: documented and declared the runtime dependency

Focused validation:

- `python -m pytest -q tests/test_pipeline.py tests/pipeline/test_agents_llm.py tests/pipeline/test_agents_concrete.py tests/pipeline/test_real_pipeline_integration.py`
- `python -m pytest -q tests/pipeline/test_graph_integration.py tests/test_cli_agentic.py`
- Result: `157 passed`

---

## File Structure

```
forged/pipeline/
├── __init__.py                  # Public API exports
├── state.py                     # PipelineState and all supporting types
├── failure.py                   # classify() — 6 failure categories
├── router.py                    # Router, RoutingBudget, budget enforcement
├── graph.py                     # build_pipeline_graph(), run_pipeline()
└── agents/
    ├── __init__.py              # Agent ABC, AgentOutput
    ├── planner.py               # PlannerAgent (LLM)
    ├── code_author.py           # CodeAuthorAgent (LLM)
    ├── executor.py              # ExecutorAgent (real notebook execution)
    ├── student.py               # StudentAgent (LLM)
    └── reviser.py               # RevisorAgent (deterministic)

tests/pipeline/
├── test_state.py                # Immutability, builders, validation
├── test_failure.py              # All 6 categories, determinism
├── test_router.py               # Budget enforcement, routing logic
├── test_agents.py               # Protocol: persona loading, fail-fast
├── test_agents_concrete.py      # Concrete agents: state transitions, artifacts
├── test_agents_llm.py           # LLM-wired agents: mock client, error handling
└── test_graph_integration.py    # Full graph: compilation, routing, E2E runs
```

---

## How to Extend

### Add a new failure category

1. Add the new value to `FailureCategory` in `forged/pipeline/failure.py`.
2. Add a matching priority check in `classify()` (early-return style, before ACCEPTABLE).
3. Add a routing rule in `Router.route()` in `forged/pipeline/router.py`.
4. Add a test in `tests/pipeline/test_failure.py` and `tests/pipeline/test_router.py`.

### Add a new agent

1. Create `forged/pipeline/agents/your_agent.py`; subclass `Agent[AgentOutput]`.
2. Implement `_load_persona()`, `next_stage()`, and `async run(state, store)`.
3. Add a persona file at `personas/your_agent.md`.
4. Wire the new node into `build_pipeline_graph()` in `graph.py`.
5. Add edge(s) and update the conditional routing mapping if needed.
6. Write tests in `tests/pipeline/test_agents_*.py`.

### Change routing budgets

Pass a custom `RoutingBudget` to `build_pipeline_graph()` (or to `RevisorAgent` directly in
tests). Default values are in `RoutingBudget` in `forged/pipeline/router.py`.
