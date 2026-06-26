# forgeducation

**A multi-agent CLI that builds — and self-checks — IT learning notebooks.**

forgeducation turns a one-line topic into a runnable Jupyter notebook by passing it
through a pipeline of role-specialised agents (planner → code author → executor →
student → reviewer → reviser …). Crucially, one stage **actually executes** the generated
notebook and captures what every cell really does, so the explanations are checked
against reality instead of assumption.

It exists to kill a specific failure mode: teaching material whose prose claims
things the code doesn't actually do.

## Why it's built this way

- **Sandboxed agents** — each agent sees only its persona and its declared inputs,
  never the others' reasoning. They behave like distinct collaborators.
- **Reality-checked** — the executor runs the notebook; the student/reviewer judge
  the *real* outputs. Regressions are caught, not shipped.
- **Reproducible** — every run writes a self-contained directory with the deliverable
  notebook, a readable summary, and a manifest.
- **Dynamic** — the "team" is a YAML file. Add, remove, or reorder stages without
  touching Python.
- **Retargetable** — *who* the lesson is for lives in one swappable profile file.
  Point it at a beginner, an expert, any environment — the whole pipeline recalibrates.
- **Local or cloud** — the same code talks to OpenAI or a local Ollama server; only
  the `base_url` differs. Point at Ollama and nothing leaves your machine.

## Honest by design

The pipeline refuses to fake teaching value. Four guarantees, each enforced by the agents and
surfaced in the run's `SUMMARY.md`:

- **Never silently drop a requested capability** (topic fidelity, "R1"). If the topic asks to set
  up *and train* a model, a run that only sets up **records** the dropped capability — it never
  quietly ships the easier lesson. (`docs/architecture/11-topic-fidelity-r1.md`)
- **Never silently assume a prerequisite.** The first notebook cell is a learner *orientation*
  that surfaces, in plain language, what the lesson assumes and the gap most likely to trip this
  learner — from the planner's per-learner KNOWN/GAP map.
  (`docs/architecture/12-notebook-orientation-cell.md`)
- **Never cram a topic past the learner's foundation.** When the prerequisite gaps are
  foundational and too deep for one honest lesson, the planner scopes down to a teachable
  beachhead and declares the rest as an honest fidelity gap — instead of dumping dense,
  unfollowable code. (`docs/architecture/14-code-explanation-and-readiness.md`)
- **Never drop or re-teach across a course.** `forged course` decomposes an over-large topic into
  ordered modules whose union must cover every requested capability, folding earlier modules'
  objectives into later modules' prior knowledge. (`docs/architecture/13-curriculum-planner.md`)

Dense code is made *followable*, not just present: a plain-words ASCII pipeline map plus a short
per-cell brief that decodes each meaningful parameter and surfaces every file the code writes.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # editable install; adds the `forged` command
cp .env.example .env        # then put your OPENAI_API_KEY in .env
```

If you also want prompt tracing, add your `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY` to `.env`. When those keys are present, every LLM-backed
agent prompt is traced automatically.

## Use

A lesson is built from a **topic** plus, optionally, two **context** files that
describe *who* it's for (a learner profile) and *what* it should cover (a topic
spec). Two engines can build it — see [Execution paths](#execution-paths). The
agentic engine is the recommended one: it runs the notebook, classifies any
failure, and re-routes to the right agent to fix it.

```bash
# 1. Minimal — just a topic; sensible defaults for everything else.
forged agentic --topic "How a Bloom filter works" --run-dir ./runs/bloom

# 2. Full context (recommended) — tailor the lesson to a specific learner + topic.
forged agentic \
    --topic "Transformer attention from scratch" \
    --learner-profile templates/examples/learner-ml-practitioner.yaml \
    --topic-spec      templates/examples/topic-transformers.yaml \
    --run-dir ./runs/transformers

# The same two context flags work on the linear engine (writes to ./runs/<ts>_<pipeline>/):
forged build \
    --topic "Recursion and the call stack" \
    --learner-profile templates/examples/learner-beginner.yaml \
    --topic-spec      templates/examples/topic-hash-maps.yaml

# Cheaper/shorter linear pipeline; list bundled pipelines; go fully local with Ollama
forged build --topic "How a Bloom filter works" --config config/pipeline.skeleton.yaml
forged pipelines
# (start `ollama serve`, set provider: ollama in the YAML — nothing leaves your machine)

# 3. Course — decompose an over-large topic into an ordered set of module notebooks.
#    --plan-only just prints/saves the decomposition (cheap: one planner call, no module runs);
#    omit it to run one lesson pipeline per module (each module's learner profile gains the
#    earlier modules' objectives as prior knowledge, so later modules aren't re-taught).
forged course --topic "Local LLM engineering on Apple Silicon" --plan-only --out ./runs/course-plan
forged course --topic "Local LLM engineering on Apple Silicon" --max-modules 1   # run modules
```

### Writing the two context files

Each flag takes a YAML file. The fastest path is to copy a ready-made one from
`templates/examples/` and edit the values:

- **Learner profiles** — `learner-beginner.yaml`, `learner-backend-junior.yaml`,
  `learner-ml-practitioner.yaml`
- **Topic specs** — `topic-hash-maps.yaml`, `topic-transformers.yaml`

Every field is **required** and the enum fields accept a **fixed set of values**
(a missing key or an unknown key fails fast before any API call). The full schema
and the allowed values for each field are documented in
**[templates/README.md](templates/README.md)**.

While a build runs it streams a live per-stage status line with an elapsed-time
spinner, so a long LLM call never looks hung.

Output lands in `./runs/<timestamp>_<pipeline>/` (or the `--run-dir` you pass to `agentic`):

- `lesson.ipynb` — the deliverable, with **real cell outputs** baked in
- `README.md` — a learner-facing guide: what the lesson teaches, who it's for, how to set
  up the environment, and how to run it
- `requirements.txt` — the pip-installable dependencies the lesson actually needs, derived
  from the plan (the same list used to provision the run's environment)
- `SUMMARY.md` — per-stage status + timing, total runtime, any execution failures or
  silent degradations, the acceptance verdict, and plan + feedback inline
- `manifest.json` — provenance (what was produced and pruned) plus per-stage timings
- `usage.json` / `USAGE.md` — per-call token usage for the run (input / output / cached /
  reasoning tokens) broken down by stage, so you can see exactly where the cost went

Intermediate plumbing (raw JSON reports, draft notebooks) is pruned automatically on
success; failed runs keep everything **and still write a `SUMMARY.md`** for debugging.

### Environment provisioning (agentic)

By default `forged agentic` reads the lesson's dependencies from the plan, builds a
**per-run virtualenv** (cached and reused across runs by a content hash of the
requirements, so heavy wheels download once), registers a Jupyter kernel, and runs the
notebook against it — so the lesson's cells execute for real instead of skipping behind
`if HAVE_DEPS:` guards. If the required packages can't be installed, the run **fails
honestly** (it never ships a green-but-empty notebook). Pass `--no-provision` to skip the
venv and run on the base kernel (fast/offline when the deps are already importable).
Provisioning only installs from a vetted package allow-list.

### Exit codes

The CLI tells the truth about what it shipped, so it's safe to wrap in a script:

| Code | Meaning |
|------|---------|
| `0` | Done. (A non-fatal "below the quality bar" warning may still print.) |
| `1` | Runtime failure, **or** a notebook shipped with a crucial issue still open — review `SUMMARY.md` before use. |
| `2` | Bad input/usage (e.g. empty `--topic`, missing `--config`) — caught before any API call. |

### Housekeeping

Run directories are never auto-deleted, and `clean` never deletes without consent:

```bash
forged clean --keep 10              # prompts: "Delete N run(s)? [y/N]"
forged clean --keep 10 --dry-run    # preview what would be removed
forged clean --keep 10 --yes        # skip the prompt (required non-interactively)
```

### Execution paths

There are two ways the pipeline can run. Both accept the same `--learner-profile`
and `--topic-spec` context files; the difference is how they iterate.

**Linear (`forged build`, simple + predictable):** runs every stage once in a fixed
sequence — planner → code_author → executor → student → reviser — followed by a bounded
revision loop. No failure classification; good when you want a deterministic single pass.

**Agentic (`forged agentic`, recommended):** a LangGraph pipeline that classifies
failures, reroutes to the appropriate agent, and feeds structured feedback back in for
intelligent iteration:

```bash
forged agentic --topic "..." --run-dir ./runs/my-lesson \
    --learner-profile path/to/learner.yaml --topic-spec path/to/topic.yaml
```

End-to-end validated with OpenAI. Features:
  - **Real executor**: runs the notebook in a kernel and detects code failures
  - **Honest signals**: a failed grader is its own signal (never a fake score), silent
    fallbacks are recorded as *degradations* in SUMMARY.md, and a deterministic structural
    gate refuses a notebook that executes green but demonstrates nothing (anti-hollow)
  - **Content reviser**: a low content-quality grade routes to an LLM agent that rewrites
    the notebook, which is then re-executed and re-graded
  - **Environment provisioning**: builds/reuses a per-run venv from the lesson's
    requirements so cells run for real (see above); `--no-provision` to opt out
  - **Self-contained deliverable**: each run ships `README.md` + `requirements.txt`
  - **Revision brief**: structured failure feedback drives smart rerouting
  - **Monitoring**: full routing log in SUMMARY.md, execution trace in pipeline.log
  - **Tracing**: every LLM-backed prompt is grouped into a Langfuse trace per run when `LANGFUSE_*` keys are configured
  - **Token accounting**: each run writes `usage.json` + `USAGE.md` — input/output/cached/reasoning
    tokens per stage, captured locally (no dashboard required)
  - **Followable dense code**: an ASCII pipeline map + per-cell briefs decode parameters and surface
    files the code writes; the planner refuses to cram a topic past the learner's foundation
  - **Exit-code truth**: exit `0` only when the run ends ACCEPTABLE; errors, budget
    exhaustion, and unclassifiable runs exit `1` (review `SUMMARY.md` before use).
    `lesson.ipynb` is the executed notebook with real cell outputs.

For detailed status, capabilities, and testing guide see [TEST.md](TEST.md) and
[docs/architecture/07-agentic-pipeline-status.md](docs/architecture/07-agentic-pipeline-status.md). For tracing specifics, see [docs/architecture/09-langfuse-tracing.md](docs/architecture/09-langfuse-tracing.md).

## Developing

New contributors: start with [DEVELOPMENT.md](DEVELOPMENT.md). It explains:
- The system architecture and data flow
- The `docs/architecture/` guide (design docs for learner profiles, input flow, implementation)
- Key concepts (profiles, topics, context threading)
- How to add agents, modify profiles, or change the CLI
- Project structure and file layout

Users: skip this and jump to [Use](#use) above.

## How it fits together

```
brief    ┐                                                   executor ─► report
profile  ┴► planner ─► plan ─► code_author ─► notebook ─►  └─► student ─► feedback
                                                          (runs it!)
            … reviser ─► executor ─► student  (the review-loop config repeats this)
```

The review-loop keeps re-revising the current best notebook until it clears the
quality bar, the iteration budget runs out, or a revision is strictly worse than
what's already in hand. It only ever **keeps the best** version, never a regression.

| Module | Responsibility |
|--------|----------------|
| `forged/config.py` | Load + validate the pipeline YAML (dataflow checked) |
| `forged/artifacts.py` | Immutable artifacts + reproducible run dirs + cleanup |
| `forged/llm.py` | Pluggable OpenAI/Ollama client |
| `forged/notebook.py` | Assemble `.ipynb` from JSON cells; index-label for agents |
| `forged/agent.py` | `LLMAgent`: persona + inputs → one output artifact |
| `forged/executor.py` | Run the notebook, capture per-cell errors (anti-bug) |
| `forged/report.py` | Human-readable `SUMMARY.md` (timing, verdict, residuals) |
| `forged/orchestrator.py` | Run + time stages, pass artifacts, finalize the run |
| `forged/packaging.py` | Write the learner-facing `README.md` + `requirements.txt` |
| `forged/provisioning.py` | Build/reuse a per-run venv from the deps; register a kernel |
| `forged/progress.py` | TTY-only elapsed-time spinner for long stages |
| `forged/context.py` | Build the shared learner+topic context block threaded to every stage |
| `forged/models.py` | Typed, validated learner profile + topic specification |
| `forged/usage.py` | Per-call token ledger → `usage.json` + `USAGE.md` |
| `forged/curriculum/` | Decompose an over-large topic into an ordered course of modules (`forged course`) |
| `forged/cli.py` | `forged build` / `agentic` / `course` / `pipelines` / `clean` |

The agentic pipeline lives under `forged/pipeline/` (state, failure classification, router,
graph, the topic-fidelity detector, and the per-role agents incl. the content reviser); see
[docs/architecture/07-agentic-pipeline-status.md](docs/architecture/07-agentic-pipeline-status.md).

Pipelines live in `config/`, agent system-prompts in `personas/`, learner profile
templates in `templates/` (ready-to-use examples in `templates/examples/`).

## Customise

- **New learner:** copy a YAML from `templates/examples/`, edit, pass `--learner-profile`.
- **New team shape:** copy a file in `config/`, add/remove/reorder stages, pass
  `--config`. A stage references upstream outputs by name; the loader fails fast if
  the dataflow is broken.
- **New role:** drop a system-prompt in `personas/`, reference it from a stage.

## Tests

```bash
pip install -e ".[dev]"
pytest -q                        # offline: no API key needed
pytest --cov=forged              # with coverage (~92%)
```

Covers config validation, notebook assembly, cell indexing, the executor catching a
failing cell, run finalization, summary generation, the acceptance gate, the bounded
revision loop, run timing, CLI input validation + exit codes, and the `clean` safety
guards (confirm / `--yes` / `--dry-run`).

## Quality checks

Lint and type-check use the same `[dev]` extra:

```bash
ruff check forged tests         # lint + import sorting
mypy                            # static type check (config in pyproject.toml)
```

## License

MIT.
