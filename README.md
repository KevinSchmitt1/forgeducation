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
- **Never drop or re-teach across a course.** An over-large topic is decomposed into
  ordered modules whose union must cover every requested capability, folding earlier modules'
  objectives into later modules' prior knowledge. With `--redecompose`, a module that *still* drops a
  capability at run time is handed back to the planner as a fresh follow-on module and run — so the
  course grows to cover the overflow instead of losing it (bounded by `--max-modules` and `--max-depth`).
  (`docs/architecture/13-curriculum-planner.md`)
- **Never force-fit code — or fake the self-check.** Not every technical topic is compute-and-show
  Python; "working with agentic AI" is really agent definitions, persona files, framework wiring and
  scaffolding. The planner **infers a lesson mode** and the run states which check it earned:
  `executable` (cells compute and are executed — the default), `artifact` (cells *build and validate*
  the deliverable — parse/lint/mocked dry-run — so the self-check still runs, only its target
  changes), or `conceptual` (prose/diagrams, and `SUMMARY.md` says plainly that no code was executed).
  Mode is inferred, never a flag. (`docs/architecture/17-lesson-modes.md`)

  > **Known limitation (updated 2026-08-16):** `artifact` lessons whose deliverable is *itself* a
  > document containing code — an agent instruction file, say — failed on the first real run: the
  > notebook embedded that content in a Python string literal, and a docstring inside the content
  > closed the literal. Fixes have landed (the revision brief now names the mechanism, and the
  > author is taught `%%writefile`, which writes verbatim), and they are validated offline against
  > that run's notebooks — **but not yet by a paid run**. Diagnosis and fixes:
  > `docs/architecture/20-artifact-lessons-that-author-documents.md`. `conceptual` has still not
  > been observed being selected on a real plan.
- **Never spend before you agree.** `forged learn` (the front door) always shows the proposed
  plan and a rough cost/time estimate and runs nothing paid until you confirm; plan tweaks are
  applied deterministically, so an interactive round never costs an expensive re-plan.
  (`docs/architecture/16-smart-front-door.md`)

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

**There is one command you run: `forged learn`.** Give it a topic; it decides whether that's a
single notebook or a short course, shows you the plan with a rough cost/time estimate, and **runs
nothing paid until you confirm**. At the prompt you type `yes`, `no`, or a change in plain language
("just make it one notebook", "combine 1 and 2", "drop module 3") — a small model turns that into a
structural edit applied deterministically, so adjusting the plan never triggers an expensive re-plan.

Optionally tailor the lesson with two **context** files describing *who* it's for (a learner profile)
and *what* it should cover (a topic spec) — see [Writing the two context files](#writing-the-two-context-files).

```bash
# The one command — plan first, confirm at the prompt, then it builds.
forged learn --topic "How to set up and train local LLMs on Apple Silicon"

# Tailored to a specific learner + topic (recommended for a real run):
forged learn \
    --topic "Transformer attention from scratch" \
    --learner-profile templates/examples/learner-ml-practitioner.yaml \
    --topic-spec      templates/examples/topic-transformers.yaml

# Non-interactive: --yes accepts the proposed plan and builds without prompting.
# A script MUST pass --yes; a non-TTY stdin without it is a usage error, so money is
# never spent silently.
forged learn --topic "How a Bloom filter works" --yes
```

Output lands in `./runs/<timestamp>_<slug>/` for a single lesson (or `./runs/<timestamp>_course_<slug>/`
for a course): open `lesson.ipynb`, read `SUMMARY.md`. Cap cost with `--max-modules N` (limit how many
course modules actually run) and `--no-provision` (skip per-lesson virtualenv building).

### Other commands

There is **one** build command — `forged learn`. It plans first and decides for itself whether your
topic is a single lesson or a course of modules, so there is nothing to choose between. The rest are
utilities:

| Command | What it's for |
|---|---|
| `forged learn --topic … --plan-only [--out DIR]` | Print the plan and its coverage verdict, then stop. Cheap (one planner call) and builds nothing — the way to see the shape of a course before spending on it. `--out` also saves `course_plan.json` + `COURSE.md`. |
| `forged pipelines` | List the bundled pipeline configs. |
| `forged clean --keep N` | Prune old run directories (asks before deleting). |

> **Removed in 2026-08:** `forged build`, `forged agentic` and `forged course`. Picking between them
> meant committing to "one lesson" or "a course" before anything had sized the topic — a judgement
> the learner had no basis to make. `forged learn` makes it, shows you the result, and waits for
> confirmation. The single-lesson and course engines are unchanged; only the way in is.

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
  silent degradations, the acceptance verdict, the lesson mode + which verification it earned
  (executed / built-and-validated / none), and plan + feedback inline
- `manifest.json` — provenance (what was produced and pruned) plus per-stage timings
- `usage.json` / `USAGE.md` — per-call token usage for the run (input / output / cached /
  reasoning tokens) broken down by stage, so you can see exactly where the cost went

Intermediate plumbing (raw JSON reports, draft notebooks) is pruned automatically on
success; failed runs keep everything **and still write a `SUMMARY.md`** for debugging.

### Environment provisioning

By default every lesson build reads the lesson's dependencies from the plan, builds a
**per-run virtualenv** (cached and reused across runs by a content hash of the
requirements, so heavy wheels download once), registers a Jupyter kernel, and runs the
notebook against it — so the lesson's cells execute for real instead of skipping behind
`if HAVE_DEPS:` guards. This happens **immediately after planning, before the notebook is
written**, so an environment that can't be built costs one cheap planner call rather than a
full authored notebook. If the required packages can't be installed, the run **fails
honestly** (it never ships a green-but-empty notebook). Pass `--no-provision` to skip the
venv and run on the base kernel (fast/offline when the deps are already importable).
Provisioning installs what the lesson plan declares, bounded by an install timeout and an
environment size cap. (There is no package allow-list: requirements come only from the
planner's machine-readable `requirements` block, never mined from prose, so an invented
package name cannot reach `pip` — see `docs/architecture/18-*.md`.)

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

### The engine (under the hood)

`forged learn` builds each lesson with the **agentic** engine — you don't pick this, it's what runs
after you confirm the plan. It's documented here for contributors.

It's a LangGraph pipeline that classifies failures, reroutes to the appropriate agent, and feeds
structured feedback back in for intelligent iteration. A course is the same engine run once per
module, with each module's objectives handed down to the next as prior knowledge.

End-to-end validated with OpenAI. Features:
  - **Real executor**: runs the notebook in a kernel and detects code failures
  - **Honest signals**: a failed grader is its own signal (never a fake score), silent
    fallbacks are recorded as *degradations* in SUMMARY.md, and a deterministic, **mode-aware**
    structural gate refuses a hollow notebook — one that executes green but demonstrates nothing
    (`executable`), or claims artifacts it never built and validated (`artifact`)
  - **Schema-locked critics**: Student and Reviewer use OpenAI JSON Schema structured
    outputs for `quality_score`/`rubric`/`blockers`/`findings`, with lenient parsing kept
    only as a fallback for local/non-structured providers
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

New contributors: start with [`CLAUDE.md`](CLAUDE.md) — it carries the architecture overview,
current state + next task, the common "how to extend" tasks (add an agent stage, add a profile
field, add a CLI command), and the conventions that matter here. Per-feature design lives in
[`docs/architecture/`](docs/architecture/) (dated snapshots); the roadmap lives in [`TODO.md`](TODO.md).

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
| `forged/executor.py` | Run the notebook, capture per-cell errors (anti-bug) |
| `forged/packaging.py` | Write the learner-facing `README.md` + `requirements.txt` |
| `forged/deliverables.py` | Per-run `SUMMARY.md`, final notebook, learner package |
| `forged/logging_config.py` | Console + per-run file logging (safe to reconfigure per module) |
| `forged/pipeline/` | The agentic graph: agents, state, router, failure classification, lesson mode |
| `forged/provisioning.py` | Build/reuse a per-run venv from the deps; register a kernel |
| `forged/progress.py` | TTY-only elapsed-time spinner for long stages |
| `forged/context.py` | Build the shared learner+topic context block threaded to every stage |
| `forged/models.py` | Typed, validated learner profile + topic specification |
| `forged/usage.py` | Per-call token ledger → `usage.json` + `USAGE.md` |
| `forged/curriculum/` | Decompose an over-large topic into an ordered course of modules |
| `forged/cli.py` | `forged learn` (the front door) / `pipelines` / `clean` |

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
