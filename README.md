# forgeducation

**A multi-agent CLI that builds — and self-checks — IT learning notebooks.**

forgeducation turns a one-line topic into a runnable Jupyter notebook by passing it
through a pipeline of role-specialised agents (planner → code author → executor →
student → reviser …). Crucially, one stage **actually executes** the generated
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

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .            # editable install; adds the `forged` command
cp .env.example .env        # then put your OPENAI_API_KEY in .env
```

## Use

```bash
# Full pipeline (plan → author → run → student → revise → re-run → re-check)
forged build --topic "How a Bloom filter works"

# Cheaper, shorter pipeline
forged build --topic "How a Bloom filter works" \
    --config config/pipeline.skeleton.yaml

# Target a specific learner
forged build --topic "Recursion and the call stack" \
    --learner-profile templates/examples/learner-beginner.yaml

# Discover the bundled pipelines (skeleton, review-loop)
forged pipelines

# Run fully local / private (start `ollama serve`, set provider: ollama in the YAML)
```

While a build runs it streams a live per-stage status line with an elapsed-time
spinner, so a long LLM call never looks hung.

Output lands in `./runs/<timestamp>_<pipeline>/`:

- `lesson.ipynb` — the deliverable, with **real cell outputs** baked in
- `SUMMARY.md` — per-stage status + timing, total runtime, any execution failures,
  the acceptance verdict, and plan + feedback inline
- `manifest.json` — provenance (what was produced and pruned) plus per-stage timings

Intermediate plumbing (raw JSON reports, draft notebooks) is pruned automatically on
success; failed runs keep everything **and still write a `SUMMARY.md`** for debugging.

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

There are two ways the pipeline can run:

**Linear (primary, stable):** `forged build` runs every stage once in a fixed sequence —
planner → code_author → executor → student → reviser. This is the path powering everything
above.

**Agentic (production-ready):** `forged agentic --brief "..." --run-dir /path` is a
LangGraph-based pipeline that classifies failures, reroutes to the appropriate agent,
and provides structured feedback for intelligent iteration. Phases 1–9 complete (292 tests,
89% coverage, end-to-end validated with OpenAI). Features:
  - **Phase 7**: Real executor detects code failures
  - **Phase 8**: Revision brief provides agent feedback for smart rerouting
  - **Phase 9**: CLI command with detailed logging and audit trail
  - **Monitoring**: Full routing log in SUMMARY.md, execution trace in pipeline.log
  - **Exit-code truth**: exit `0` only when the run ends ACCEPTABLE; errors, budget
    exhaustion, and unclassifiable runs exit `1` (review `SUMMARY.md` before use).
    `lesson.ipynb` is the executed notebook with real cell outputs.

For detailed status, capabilities, and testing guide see [TEST.md](TEST.md) and
[docs/architecture/07-agentic-pipeline-status.md](docs/architecture/07-agentic-pipeline-status.md).

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
| `forged/progress.py` | TTY-only elapsed-time spinner for long stages |
| `forged/cli.py` | `forged build` / `pipelines` / `clean` |

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
