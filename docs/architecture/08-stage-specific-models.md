# Stage-Specific Models — Implementation Session

**As of:** 2026-06-14  
**Scope:** Add stage-specific model defaults for both linear and agentic pipelines  
**Status:** Implemented and validated

---

## Overview

This session added a shared model-resolution layer so the repo no longer relies on
one implicit LLM default for all stages.

Before this change:

- The **linear pipeline** already supported per-stage model overrides through YAML,
  but there was no shared logical-stage default map.
- The **agentic pipeline** constructed LLM-backed agents with a bare `ModelConfig()`,
  so Planner, CodeAuthor, and Student all defaulted to the same model unless code
  was changed.
- The **linear reviser** inherited its model indirectly from the latest notebook-
  producing stage instead of resolving its own explicit model.

After this change:

- Both execution paths resolve models through the same `PipelineConfig` API.
- Bundled pipeline YAML now declares stage-specific defaults directly.
- The agentic CLI loads a pipeline config and passes it into LangGraph graph
  construction.
- The linear reviser resolves its own configured model explicitly.

This session intentionally stops at configuration plumbing. The Langfuse tracing
follow-up now lives in `09-langfuse-tracing.md`.

---

## Goals

1. Make stage-specific model selection possible in the **agentic** path.
2. Keep model resolution consistent between **linear** and **agentic** pipelines.
3. Encode the agreed bundled defaults directly in YAML.
4. Preserve existing override precedence and keep the change testable.

---

## Implemented Design

### Shared resolution layer

`PipelineConfig` now supports two levels of model configuration:

- `defaults`: pipeline-wide fallback model configuration
- `stage_models`: logical-stage defaults keyed by role name (`planner`,
  `code_author`, `student`, `reviewer`, `reviser`)

Resolution precedence is:

1. explicit `stage.model`
2. `stage_models[stage_name]`
3. `defaults`

Two resolver entry points are now available:

- `resolved_model(stage: StageConfig)` for concrete declared stages
- `resolved_model_name(stage_name: str)` for logical/synthesized stages

The second entry point is what unblocks:

- agentic graph agent construction
- the synthesized linear revision-loop reviser

### Agentic pipeline wiring

The agentic CLI now loads a pipeline YAML via `--config` just like the linear CLI.
That config is passed into `run_pipeline(...)`, and `build_pipeline_graph(...)`
constructs LLM clients with stage-specific resolved models for:

- Planner
- CodeAuthor
- Student

The deterministic Revisor remains non-LLM and therefore ignores model config.

### Linear revision-loop wiring

The revision loop no longer infers the reviser model from the latest notebook-
producing stage. It now resolves `reviser` explicitly through
`PipelineConfig.resolved_model_name("reviser")`.

This removes hidden coupling between CodeAuthor and Reviser model choice.

---

## Bundled Defaults

The bundled pipeline configs now encode the following defaults:

| Logical stage | Default model |
|---|---|
| `planner` | `gpt-5-mini` |
| `code_author` | `gpt-5` |
| `student` | `gpt-5-mini` |
| `reviewer` | `gpt-5-mini` |
| `reviser` | `gpt-5` |

Pipeline-wide fallback default:

- `gpt-5-mini`

Rationale:

- **CodeAuthor** gets the strongest model because code quality has the highest
  downstream leverage.
- **Reviser** in the linear path also gets a strong model because it rewrites the
  notebook artifact directly.
- **Planner**, **Student**, and **Reviewer** use a smaller model to control cost
  while preserving acceptable reasoning quality.

---

## Files Changed

### Core implementation

- `forged/config.py`
  - added `stage_models`
  - added `resolved_model_name(stage_name)`
  - preserved stage override precedence

- `forged/cli.py`
  - added `--config` support to `forged agentic`
  - loads pipeline config for agentic runs
  - passes config into `run_pipeline(...)`

- `forged/pipeline/graph.py`
  - `build_pipeline_graph(...)` now requires `PipelineConfig`
  - injects stage-specific `LLMClient` instances for Planner, CodeAuthor, Student

- `forged/orchestrator.py`
  - linear revision loop now resolves `reviser` explicitly by logical stage name

### Bundled configs

- `config/pipeline.review-loop.yaml`
- `config/pipeline.skeleton.yaml`

Both now define `stage_models` and default to the agreed mixed-model setup.

### Tests

- `tests/test_pipeline.py`
  - validates bundled defaults and resolver precedence

- `tests/test_cli_agentic.py`
  - validates that the agentic CLI loads pipeline config and passes it into the
    graph runner

- `tests/pipeline/test_graph_integration.py`
  - validates graph construction uses stage-specific configured models
  - updated async test execution to `asyncio.run(...)`

---

## Validation

Focused validation executed after implementation:

```bash
python -m pytest -q tests/test_pipeline.py tests/test_cli_agentic.py tests/pipeline/test_graph_integration.py
```

Result:

- `99 passed`

Code review outcome:

- No implementation findings beyond one runtime caveat about whether the target
  OpenAI account exposes the configured `gpt-5` / `gpt-5-mini` identifiers.

---

## Known Caveat

This implementation assumes that the configured OpenAI model names are valid for
the runtime environment:

- `gpt-5`
- `gpt-5-mini`

If an account does not expose those identifiers, the configuration layer will still
work correctly, but API calls will fail at runtime with a model-not-found error.

This is a deployment/runtime concern, not a config-resolution bug.

---

## What This Enables Next

With stage-specific model configuration in place, the tracing follow-up could add
model-level observability without redesigning the pipeline APIs. That follow-up is
now implemented in `09-langfuse-tracing.md`.

Recommended next step:

1. Surface trace ids / trace URLs inside run artifacts or summaries.
2. Compare notebook quality and cost across different model mixes.

Related docs kept in sync with this session:

- `TODO.md` — roadmap now treats trace linking and model comparison as the next observability tasks
- `DEVELOPMENT.md` — contributor guide now points to this file for model selection
- `07-agentic-pipeline-status.md` — current-status doc now includes this follow-up
- `09-langfuse-tracing.md` — implementation note for the tracing layer

---

## Summary

This session converted model choice from an implicit per-path default into an
explicit, shared configuration capability.

The key outcome is architectural consistency:

- **linear** and **agentic** paths now resolve models from the same config system
- logical stages can have different defaults without code edits
- the repo is ready for later observability work around model/version comparisons