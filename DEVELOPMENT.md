# Development Guide

Welcome! This guide helps you understand the codebase and contribute effectively.

## For New Developers

**Start here:** Read [How It Fits Together](#how-it-fits-together) below, then pick a task.

### Quick Navigation

| I want to... | Read this |
|---|---|
| Understand the system architecture | [Architecture Docs](#architecture-documentation) |
| Add a new agent stage | `docs/architecture/02-agent-input-flow.md` + `docs/architecture/03-implementation-plan.md` |
| Modify how learner profiles work | `docs/architecture/01-input-specification.md` + `templates/README.md` |
| Change the CLI | Check `forged/cli.py` + `docs/architecture/03-implementation-plan.md` |
| Understand model selection | `docs/architecture/08-stage-specific-models.md` |
| Understand tracing / token usage | `docs/architecture/09-langfuse-tracing.md` + `forged/usage.py` (`usage.json`/`USAGE.md`) |
| Add a new data model | `forged/models.py` + `docs/architecture/01-input-specification.md` |
| Understand the template system | `templates/README.md` (user guide) + `docs/architecture/01-input-specification.md` (design) |
| Understand the honesty guarantees | topic fidelity `docs/architecture/11-topic-fidelity-r1.md`; orientation `…/12-…`; readiness + code maps `…/14-…` |
| Work on the curriculum planner (`forged course`) | `docs/architecture/13-curriculum-planner.md` + `forged/curriculum/` |
| Change agent behaviour / pedagogy | edit `personas/*.md` (most quality changes are persona edits, not code) |

## How It Fits Together

```
User Input                           Pipeline Execution
┌─────────────────────────────┐     ┌────────────────────────────┐
│ topic                       │     │ stage 1: planner           │
│ --learner-profile (opt)     │ ──► │   ↓                        │
│ --topic-spec (opt)          │     │ stage 2: code_author       │
│                             │     │   ↓                        │
└─────────────────────────────┘     │ stage 3: executor          │
                                    │   (runs notebook)          │
                                    │   ↓                        │
                                    │ stage 4+: student/reviewer │
                                    │           /reviser         │
                                    │                            │
                                    └────────────────────────────┘
                                           ↓
                                    Output: lesson.ipynb
                                           SUMMARY.md
                                           manifest.json
```

## Agentic Pipeline Status

The repo contains two execution paths, plus a course layer above them:

1. **Linear CLI** (`forged build`): the primary, stable, user-facing path in
   [forged/cli.py](forged/cli.py). Use this for real lesson generation.
2. **Agentic CLI/API** (`forged agentic` or `await forged.pipeline.run_pipeline(...)`): a LangGraph-based pipeline in [forged/pipeline/](forged/pipeline) that classifies failures and reroutes to the appropriate agent. Phases 1–9 are complete, stage-specific model defaults are configured through pipeline YAML, and every LLM-backed prompt is traced to Langfuse when credentials are present; see [docs/architecture/08-stage-specific-models.md](docs/architecture/08-stage-specific-models.md) and [docs/architecture/09-langfuse-tracing.md](docs/architecture/09-langfuse-tracing.md).
3. **Curriculum layer** (`forged course`): a composition layer *above* the unchanged lesson loop in [forged/curriculum/](forged/curriculum). It decomposes an over-large topic into an ordered course of modules (`--plan-only` to just plan) and runs each module through the agentic `run_pipeline`, folding earlier modules' objectives into later modules' prior knowledge. Phases 1–2 done; see [docs/architecture/13-curriculum-planner.md](docs/architecture/13-curriculum-planner.md).

### What is implemented (Phases 1–9)

- **Immutable state schema** (`PipelineState`) with full audit trail in `routing_log`
  and an explicit `terminal_ok` success flag (terminal ≠ success).
- **Deterministic failure classification** across 6 categories: `BLOCKER_STRUCTURE`,
  `CODE_QUALITY`, `TEST_FAILURE`, `CONTENT_QUALITY`, `ACCEPTABLE`, `UNCLASSIFIABLE`.
- **Budget-aware routing** that terminates rather than looping indefinitely.
- **Agents**: Planner, CodeAuthor, Executor (real notebook execution), Student (learner-POV
  critic), **Reviewer** (expert correctness/quality critic), Reviser (deterministic router),
  and **ContentReviser** (LLM prose rewriter) — all wired into a compiled LangGraph. The two
  critics (Student + Reviewer) run before the Reviser, which merges their findings before
  classifying. LLM agents degrade gracefully on error; a hard agent failure marks
  the state terminal and stops the graph immediately.
- **Honest signals** (output-quality remediation): a failed grader is its own signal, not
  a fake score; rubric-dimensioned student grades; silent fallbacks are recorded as
  `degradations` on the state and surfaced in SUMMARY.md; and a deterministic structural
  gate (`forged/pipeline/structure.py`) refuses an executed-but-hollow notebook.
- **Structured grader outputs**: Student and Reviewer pass strict OpenAI JSON Schema
  response formats through `LLMClient.complete(...)` so the cheap critic stages return
  machine-parseable `blockers`/`findings` (and student `quality_score`/`rubric`). Ollama
  omits `response_format`, so the existing lenient parsers remain the local-provider
  fallback rather than the primary contract.
- **Self-contained deliverable**: `forged/packaging.py` writes a learner `README.md` +
  `requirements.txt`; `forged/provisioning.py` builds/reuses a content-addressed per-run
  venv so cells run for real (default-on; `--no-provision` opts out).
- **Revision briefs** (`revision_brief_v{N}.md`): structured failure feedback that
  rerouted agents read on their next pass.
- **CLI command** (`forged agentic --topic ... --run-dir ...`) with honest exit codes:
  `0` only when the run ends ACCEPTABLE; errors/budget exhaustion exit `1`.
- **Tests passing; `ruff` + `mypy` clean**; `state.py`, `failure.py`, `router.py`,
  `structure.py`, `dependencies.py`, `packaging.py`, `content_reviser.py` at ~100%.
- **End-to-end validated** with a real `OPENAI_API_KEY`; both linear and agentic paths
  complete successfully, `tests/pipeline/test_real_pipeline_integration.py` covers the
  un-mocked CodeAuthor → executor contract, and provisioning was validated by a real run
  (see [docs/architecture/10-output-quality-remediation.md](docs/architecture/10-output-quality-remediation.md)).

### Known limitations

- Budget exhaustion still writes `lesson.ipynb` (latest notebook), but the run exits
  non-zero — review `SUMMARY.md` before use.
- Per-dimension routing is partial: a low *content* grade routes to the ContentReviser,
  but full rubric-dimension → stage routing (e.g. low `code_clarity` → CodeAuthor) is a
  later refinement; the cascade still routes structure/code via BLOCKER/HIGH findings.
- Provisioning installs only from a vetted package allow-list
  (`forged/provisioning.py`); a lesson needing a package outside it fails honestly rather
  than installing arbitrary code — extend the allow-list intentionally.

For complete details — capabilities, limitations, and the Phase 7–9 roadmap — see
[docs/architecture/07-agentic-pipeline-status.md](docs/architecture/07-agentic-pipeline-status.md).
For the model-configuration follow-up, see
[docs/architecture/08-stage-specific-models.md](docs/architecture/08-stage-specific-models.md).
For tracing and observability details, see
[docs/architecture/09-langfuse-tracing.md](docs/architecture/09-langfuse-tracing.md).

### Data Flow

1. **User provides input** → `--topic`, optional `--learner-profile`, `--topic-spec`
2. **CLI parses input** → loads YAML files, creates data models (LearnerProfile, TopicSpecification)
3. **Orchestrator threads context** → passes learner profile + topic spec through pipeline
4. **Each agent renders prompts** → uses context to customize explanations for learner
5. **Pipeline stages run** → planner → code_author → executor → student → reviewer → reviser (if enabled)
6. **Output is generated** → `lesson.ipynb` with real cell outputs, `SUMMARY.md` with feedback

## Architecture Documentation

The `docs/architecture/` directory contains design decisions and implementation details:

### 01-input-specification.md
**What:** Design of learner profiles and topic specifications  
**Why:** Explains the pedagogical reasoning behind each field  
**For:** Understanding what data we collect and why  
**Read if:** You're adding new fields to learner profiles or topic specs

### 02-agent-input-flow.md
**What:** How context flows through agents; which agent uses which fields  
**Why:** Shows the full data path from input to agent prompts  
**For:** Understanding which agent sees what information  
**Read if:** You're modifying an agent or adding a new stage

### 03-implementation-plan.md
**What:** Detailed file-by-file code changes for the input specification system  
**Why:** Complete implementation walkthrough with decisions explained  
**For:** Understanding how the code is structured  
**Read if:** You're working on models.py, cli.py, orchestrator.py, or agent.py

### 07-agentic-pipeline-status.md
**What:** Current implemented state of the LangGraph agentic pipeline  
**Why:** Captures what is done, what is stable, and which limitations remain  
**For:** Understanding the actual agentic architecture in the repo today  
**Read if:** You're changing routing, graph wiring, agentic CLI behavior, or revision flow

### 08-stage-specific-models.md
**What:** Shared model-resolution design for linear + agentic execution paths  
**Why:** Explains how model defaults, logical stage models, and overrides now work  
**For:** Understanding or changing per-stage model/provider selection  
**Read if:** You're changing model configuration, adding tracking, or running model comparisons

### 09-langfuse-tracing.md
**What:** Langfuse tracing implementation for linear + agentic LLM calls  
**Why:** Explains where traces are created, what metadata is attached, and what is still missing  
**For:** Understanding observability for prompts, model usage, and run-level grouping  
**Read if:** You're changing tracing, adding trace links to artifacts, or debugging Langfuse setup

## Project Structure

```
forged/
├── forged/                   # Main package
│   ├── __init__.py
│   ├── cli.py                  # CLI entry point; parses --topic, --learner-profile, etc.
│   ├── orchestrator.py         # Runs the pipeline; threads context through stages
│   ├── agent.py                # LLMAgent base class; renders context-aware prompts
│   ├── executor.py             # Executor stage; runs the notebook
│   ├── artifacts.py            # Store, notebook management
│   ├── models.py               # Data models: LearnerProfile, TopicSpecification
│   ├── context.py              # Shared learner/topic prompt-context rendering
│   ├── progress.py             # Spinner for live progress display
│   ├── config.py               # Config file loading
│   ├── packaging.py            # Writes learner README.md + requirements.txt
│   ├── provisioning.py         # Per-run venv build/reuse (content-addressed cache)
│
│   └── pipeline/               # Agentic pipeline package
│       ├── state.py            # Immutable agentic state + audit trail
│       ├── failure.py          # Deterministic failure classification (+ rubric)
│       ├── structure.py        # Deterministic anti-hollow structural gate
│       ├── dependencies.py     # Extract requirements from the plan (+ hash)
│       ├── router.py           # Budget-aware routing
│       ├── graph.py            # LangGraph assembly + execution entrypoints
│       └── agents/             # Planner/CodeAuthor/Executor/Student/Reviewer/Reviser/ContentReviser
│
├── templates/                  # User-facing template files
│   ├── README.md               # User guide: how to customize templates
│   ├── learner_profile.template.yaml
│   ├── topic_specification.template.yaml
│   └── examples/               # Ready-to-use examples
│       ├── learner-beginner.yaml
│       ├── learner-backend-junior.yaml
│       ├── learner-ml-practitioner.yaml
│       ├── topic-hash-maps.yaml
│       └── topic-transformers.yaml
│
├── docs/
│   └── architecture/           # Design & implementation docs
│       ├── 01-input-specification.md
│       ├── 02-agent-input-flow.md
│       ├── 03-implementation-plan.md
│       ├── 07-agentic-pipeline-status.md
│       ├── 08-stage-specific-models.md
│       └── 09-langfuse-tracing.md
│
├── config/                     # Pipeline configurations
│   ├── pipeline.review-loop.yaml     # Full pipeline with revisions
│   └── pipeline.skeleton.yaml        # Minimal pipeline
│
├── personas/                   # Agent personas (system prompts)
│   ├── planner.md
│   ├── code_author.md
│   └── ...
│
├── tests/                      # Test suite
│   └── ...
│
├── .env.example                # Example .env (copy to .env and add API keys)
├── pyproject.toml              # Package config; entry point: forged command
├── README.md                   # User-facing documentation
└── DEVELOPMENT.md              # This file
```

## Key Concepts

### Learner Profile
Describes the learner's background, goals, and preferences. Controls explanation depth, examples, and pacing.

**Fields:** prior_knowledge, learning_style, environment, material_density, background_context

**Location:** `templates/examples/learner-*.yaml` (user files) or `forged/models.py` (code)

**Used by:** All agents (Planner, CodeAuthor, Student, Reviewer, Reviser) to tailor explanations

### Topic Specification
Defines what should be learned: scope, objectives, prerequisites, constraints, depth.

**Fields:** title, scope, learning_objectives, prerequisites, constraints, depth, focus_areas

**Location:** `templates/examples/topic-*.yaml` (user files) or `forged/models.py` (code)

**Used by:** Planner (structure), CodeAuthor (examples), Student (validation), Reviewer (correctness), Reviser (feedback)

### Context
Rendered learner-profile + topic-spec markdown block passed through the pipeline so agents can tailor explanations consistently.

**Example keys:** prior_knowledge, material_density, learning_objectives, depth, focus_areas

**Created by:** CLI (`build_context_block()` in `forged/context.py`)
**Consumed by:** Linear `LLMAgent` and agentic pipeline agents via the `lesson_context` artifact

## Common Tasks

### Add a New Agent Stage

1. Decide whether the new stage belongs in the linear path, the agentic path, or both.
2. For the linear path, add or adapt a stage runner via `forged/agent.py` / `forged/orchestrator.py` and YAML config.
3. For the agentic path, create a new class in `forged/pipeline/agents/your_stage.py`.
4. Add a persona file in `personas/your_stage.md`
5. Add stage to the relevant pipeline YAML in `config/`
6. Update `forged/pipeline/graph.py` if the agentic graph needs a new node/edge
7. Add tests for routing, artifacts, and prompt inputs

**References:** `docs/architecture/02-agent-input-flow.md`, `docs/architecture/07-agentic-pipeline-status.md`

### Modify the Learner Profile

1. Add field to `LearnerProfile` dataclass in `forged/models.py`
2. Update `templates/learner_profile.template.yaml` with description
3. Update `templates/examples/learner-*.yaml` with values for that field
4. Update `_default_learner_profile()` in `cli.py` to include a default
5. Update `to_prompt_context()` in models.py if the field needs special formatting
6. Update relevant prompts in `forged/prompts.py` to reference the new field
7. Update `templates/README.md` to explain the new field

**References:** `docs/architecture/01-input-specification.md`

### Change the CLI

1. Add argument to `_build_parser()` in `forged/cli.py`
2. Update `_cmd_build()` to handle the new argument
3. Update help text and docstrings
4. Test: `python -m forged.cli --help`

**References:** `docs/architecture/03-implementation-plan.md`

## Testing

Run the test suite:
```bash
pytest
pytest --cov=forged          # with coverage
pytest -v                       # verbose
```

## Session Notes

Key implementation sessions are documented in `docs/architecture/`.

- `07-agentic-pipeline-status.md` — implemented agentic pipeline and limitations
- `08-stage-specific-models.md` — model-resolution follow-up and bundled defaults

Use these first for design rationale and current-state questions.

## For Contributors

1. Read this file (you are here)
2. Find your task in "Common Tasks" above
3. Read the relevant architecture doc
4. Look at existing code for patterns
5. Write tests first (TDD)
6. Run `pytest --cov=forged` to verify coverage
7. Update session notes or README if you discover something new

## Questions?

- **Architecture questions:** Check `docs/architecture/`
- **Code questions:** Check docstrings and type hints
- **Template questions:** Check `templates/README.md`
- **Session context:** Check `.sessions/` for design decisions
- **User questions:** See main `README.md`
