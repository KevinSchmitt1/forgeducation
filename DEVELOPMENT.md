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
| Add a new data model | `forged/models.py` + `docs/architecture/01-input-specification.md` |
| Understand the template system | `templates/README.md` (user guide) + `docs/architecture/01-input-specification.md` (design) |

## How It Fits Together

```
User Input                           Pipeline Execution
┌─────────────────────────────┐     ┌────────────────────────────┐
│ topic                       │     │ stage 1: planner           │
│ --learner-profile (opt)     │ ──► │   ↓                        │
│ --topic-spec (opt)          │     │ stage 2: code_author       │
│ --assessment (opt)          │     │   ↓                        │
└─────────────────────────────┘     │ stage 3: executor          │
                                    │   (runs notebook)          │
                                    │   ↓                        │
                                    │ stage 4+: student/reviser  │
                                    │                            │
                                    └────────────────────────────┘
                                           ↓
                                    Output: lesson.ipynb
                                           SUMMARY.md
                                           manifest.json
```

## Agentic Pipeline Status

The repo contains two execution paths:

1. **Linear CLI** (`forged build`): the primary, stable, user-facing path in
   [forged/cli.py](forged/cli.py). Use this for real lesson generation.
2. **Agentic CLI/API** (`forged agentic` or `await forged.pipeline.run_pipeline(...)`):
   a LangGraph-based pipeline in [forged/pipeline/](forged/pipeline) that classifies
   failures and reroutes to the appropriate agent. Phases 1–9 are complete.

### What is implemented (Phases 1–9)

- **Immutable state schema** (`PipelineState`) with full audit trail in `routing_log`
  and an explicit `terminal_ok` success flag (terminal ≠ success).
- **Deterministic failure classification** across 6 categories: `BLOCKER_STRUCTURE`,
  `CODE_QUALITY`, `TEST_FAILURE`, `CONTENT_QUALITY`, `ACCEPTABLE`, `UNCLASSIFIABLE`.
- **Budget-aware routing** that terminates rather than looping indefinitely.
- **Five agents**: Planner, CodeAuthor, Executor (real notebook execution), Student,
  Reviser — all wired into a compiled LangGraph. LLM agents degrade gracefully on error;
  a hard agent failure marks the state terminal and stops the graph immediately.
- **Revision briefs** (`revision_brief_v{N}.md`): structured failure feedback that
  rerouted agents read on their next pass.
- **CLI command** (`forged agentic --brief ... --run-dir ...`) with honest exit codes:
  `0` only when the run ends ACCEPTABLE; errors/budget exhaustion exit `1`.
- **292 tests passing, 89% overall coverage**; `state.py`, `failure.py`, `router.py` at 100%.
- **End-to-end validated** with a real `OPENAI_API_KEY`; both linear and agentic paths
  complete successfully, and `tests/pipeline/test_real_pipeline_integration.py` covers
  the un-mocked CodeAuthor → executor contract.

### Known limitations

- `CONTENT_QUALITY` routes to the Reviser, but the agentic Reviser is deterministic and
  does not rewrite prose — the route is a no-op that exhausts the reviser budget (1) and
  terminates. A prose-rewriting agent is future work.
- Budget exhaustion still writes `lesson.ipynb` (latest notebook), but the run exits
  non-zero — review `SUMMARY.md` before use.

For complete details — capabilities, limitations, and the Phase 7–9 roadmap — see
[docs/architecture/07-agentic-pipeline-status.md](docs/architecture/07-agentic-pipeline-status.md).

### Data Flow

1. **User provides input** → `--topic`, optional `--learner-profile`, `--topic-spec`
2. **CLI parses input** → loads YAML files, creates data models (LearnerProfile, TopicSpecification, AssessmentApproach)
3. **Orchestrator threads context** → passes learner profile + topic spec through pipeline
4. **Each agent renders prompts** → uses context to customize explanations for learner
5. **Pipeline stages run** → planner → code_author → executor → student → reviser (if enabled)
6. **Output is generated** → `lesson.ipynb` with real cell outputs, `SUMMARY.md` with feedback

## Architecture Documentation

The `docs/architecture/` directory contains design decisions and implementation details:

### 01-input-specification.md
**What:** Design of learner profiles, topic specifications, and assessment approaches  
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
│   ├── models.py               # Data models: LearnerProfile, TopicSpecification, AssessmentApproach
│   ├── prompts.py              # Prompt templates for each stage
│   ├── progress.py             # Spinner for live progress display
│   └── config.py               # Config file loading
│
├── templates/                  # User-facing template files
│   ├── README.md               # User guide: how to customize templates
│   ├── learner_profile.template.yaml
│   ├── topic_specification.template.yaml
│   ├── assessment_approach.template.yaml
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
│       └── 03-implementation-plan.md
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

**Used by:** All agents (Planner, CodeAuthor, Student, Reviser) to tailor explanations

### Topic Specification
Defines what should be learned: scope, objectives, prerequisites, constraints, depth.

**Fields:** title, scope, learning_objectives, prerequisites, constraints, depth, focus_areas

**Location:** `templates/examples/topic-*.yaml` (user files) or `forged/models.py` (code)

**Used by:** Planner (structure), CodeAuthor (examples), Student (validation), Reviser (feedback)

### Assessment Approach
Optional configuration for generating project specs or knowledge tests.

**Fields:** type (project/test/both), difficulty, project spec, test spec

**Location:** `templates/assessment_approach.template.yaml` (user file) or `forged/models.py` (code)

**Used by:** AssessmentStage (new stage that runs after revisions)

### Context
Dictionary passed through the pipeline containing rendered learner profile + topic spec. Each agent uses relevant fields to customize prompts.

**Example keys:** prior_knowledge, material_density, learning_objectives, depth, focus_areas

**Created by:** CLI (via models.to_prompt_context())
**Consumed by:** Agents (in prompts via {placeholder} syntax)

## Common Tasks

### Add a New Agent Stage

1. Create a new class in `forged/agents/your_stage.py`
2. Inherit from `LLMAgent`
3. Override `run(brief, context)` → return (report, artifact)
4. Add a persona file in `personas/your_stage.md`
5. Add stage to pipeline YAML in `config/pipeline.yaml`
6. Update `orchestrator.py` to instantiate your stage
7. Add docstring explaining what context fields your stage uses

**References:** `docs/architecture/02-agent-input-flow.md`, `docs/architecture/03-implementation-plan.md`

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

Development sessions are documented in `.sessions/` for context and decision-making:

- `SESSION-2026-06-06-input-layer-implementation.md` — Input specification design and code implementation
- `SESSION-2026-06-07-template-creation-and-testing.md` — Template files and backward compatibility testing

Check these for design rationale and blockers encountered.

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
