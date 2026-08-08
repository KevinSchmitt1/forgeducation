# CLAUDE.md — working notes for agents in this repo

forgeducation is a multi-agent CLI that turns a one-line topic into a **runnable, self-checked**
teaching notebook. The defining idea: one stage **actually executes** the generated notebook and
captures what every cell really does, so explanations are checked against reality, not assumption.

This file is repo-specific orientation + the conventions that aren't obvious from the code. General
coding/testing/git style is assumed (see your global rules); this covers what's particular to here.

## Architecture at a glance

**There is one command.** `forged learn --topic "…"` plans first, and the CurriculumPlanner — not
the caller — decides whether the topic is one lesson or a course of modules. You confirm the plan at
an interactive gate before anything paid runs. The old `build` / `agentic` / `course` commands were
removed (2026-08-08): choosing between them asked the learner to pre-commit to a shape before
anything had sized the topic, and getting it wrong is what produced over-large lessons. `pipelines`
and `clean` remain as utilities.

Both branches below are reached from `learn`, and share the same agents, personas, and context block:

- **Single lesson** (1-module plan → `_run_agentic_lesson`) — a LangGraph pipeline that classifies
  failures and reroutes. Flow:
  `planner → code_author → executor → student → reviewer → revisor → (content_reviser | replan | END)`
  - **Two critics** run before the deterministic router: **Student** (learner POV — "could I follow
    this?") and **Reviewer** (expert correctness/quality). The **Reviser** is *not* a critic — it's a
    deterministic classifier/router that **merges both critics' findings** before `classify()`.
    **ContentReviser** is the LLM that rewrites prose for the `CONTENT_QUALITY` route.
  - Routing is deterministic (`router.py` + `failure.py`); a finding's **scope** (`plan`/`structure`/
    `code`/`content`) decides where it's sent. Scope tagging matters a lot — see R1 below.
  - **Lesson modes** (`mode.py`, doc 17): the planner infers `executable` (default — compute-and-show,
    executed) / `artifact` (cells *build and validate* files/config/scaffold) / `conceptual` (prose,
    nothing runs) and declares it in a ` ```lesson-mode ` block (mirrors ` ```requirements `). The
    reviser extracts it and threads it into `assess_structure()` + `classify()` so the anti-hollow gate
    is **mode-aware**; the grader personas judge artifact lessons on their terms. Purely inferred — no
    user flag, no state field. Executable behavior is unchanged.
- **Course** (N-module plan → `forged/curriculum/orchestrator.py`) — runs each module through the
  *unchanged* single-lesson pipeline, folding earlier modules' objectives into later modules'
  `prior_knowledge` (the context hand-down), then assembles the index/COURSE.md/NAV.md deliverables.

> The **linear** engine (`orchestrator.py`, `agent.py`, `gate.py`, `report.py`) was deleted with the
> `build` command. If you find a doc or comment referring to a "linear path", it is stale.

Agents are thin Python wrappers; their behavior lives in **`personas/*.md`** (planner, code_author,
student, reviewer, reviser). Most quality/pedagogy changes are persona edits, not code.

A `provision_gate` node **between the planner and the code author** builds a per-run venv from the
planner's `requirements` block (content-addressed cache under `runs/.venv-cache/`) and registers a
kernel, so an unbuildable environment costs one gpt-5-mini call instead of a full gpt-5 notebook. The
executor re-resolves the same kernel (a cache hit) because `content_reviser → executor` re-enters
execution without passing the planner. `--no-provision` skips both and runs in the base `python3`
kernel. There is **no package allow-list** — any package the plan asks for is installed; only an
install timeout and an environment size cap apply.

### Where things live
- `forged/pipeline/` — agents, graph, state, router, failure classification, lesson-mode inference
  (`mode.py`), provisioning hook
- `personas/` — the system prompts that define each agent
- `config/pipeline.*.yaml` — stage→model resolution (planner/student/reviewer = gpt-5-mini; code_author/reviser = gpt-5)
- `docs/architecture/` — design of record; last file is most of the time the most recent work, what was done.
- `TODO.md` — roadmap and current priorities

## Running & verifying

Use the project venv explicitly (the shell's active venv is often something else):

```bash
.venv/bin/python -m pytest                 # full suite (~2–5 min; some tests run real notebooks)
.venv/bin/ruff check forged tests          # CI gate 1
.venv/bin/mypy                             # CI gate 2
.venv/bin/python -m pytest --cov=forged --cov-fail-under=80   # CI gate 3 (must stay ≥80%)
```

CI (`.github/workflows/ci.yml`) runs exactly those three on every PR. Run all three before claiming
green — `pytest` passing does **not** catch ruff line-length (E501) failures.

## Verification discipline (written 2026-07-30, after a bad session)

The three gates are **necessary, not sufficient**, and treating them as sufficient caused every
avoidable failure in the doc-18 work: a `NameError` that made the CLI unable to start reached
`master` through 700 passing tests, clean ruff and clean mypy, because nothing in CI — and nobody —
had ever started the program. Four norms, in order of how much they'd have prevented:

1. **"Ready" means exercised, not green.** Before saying a change is ready, run the program the way
   a user runs it (`python -m forged.cli …`), once. Most paths cost nothing: `--help`, `pipelines`,
   an empty `--topic` (usage error). Tests `import forged.cli`; users run `-m`, where `main()`
   executes at the `__main__` guard — a difference no unit test can see.
2. **State which level of confidence you're handing over.** Three distinct things, never conflated:
   *tests green* (proxies pass) · *exercised* (I ran it) · *validated* (a real run used it). Say
   which one applies. "CI passed, ready to merge" that means only the first is how broken code gets
   merged on a reasonable decision — the fix is precise reporting, not more scrutiny from the reader.
3. **Batch merges against validation, not against CI.** The only test that means anything here is a
   paid run. Merging as soon as CI is green buys nothing and fragments history: four PRs merged in
   one afternoon, three of them fixing the previous one, none exercised by a run. Hold related
   changes on one branch, do one run, merge what survives.
4. **A repeated concern from the user is decisive.** If the same objection is raised twice, stop
   defending the position: either do it their way, or lay out the tradeoff plainly for them to
   decide. The package allow-list was questioned twice, defended twice, and cost two paid module
   builds before being removed — the objection was right the first time.

Two narrower habits, each the direct mechanism behind a real mistake here:

- **When a change removes the *reason* for an existing safeguard, re-evaluate the safeguard in the
  same change.** Deleting the requirements prose-miner removed the entire justification for the
  package allow-list; the list was kept and widened in that very PR.
- **Before citing a program's own output as evidence, test that the measurement is valid.** A
  `⚠ DROPPED` fidelity line went into a design doc as proof of topic drift; a five-line script later
  showed the check was structurally incapable of passing on a free-text topic. It was cheap to
  verify and skipped because it confirmed what was already believed.

Process degrades under momentum — that is exactly when these get skipped. Prefer a mechanical guard
(a test that fails) over a norm whenever one is available.

## Conventions that matter here

- **Immutability is enforced, not aspirational.** Never mutate `PipelineState` — go through its
  `with_*` builders. Value objects are `@dataclass(frozen=True)`; prefer tuples over lists in them.
- **TDD per change**; keep the suite green at every step. New agent behavior gets a test (e.g. routing
  outcomes, parse/degrade paths).
- **Cost discipline.** LLM stages cost money: gpt-5 (code_author/reviser) is the expensive one;
  gpt-5-mini (planner/student/reviewer) is cheap. A real paid+network E2E needs user consent — keep it
  to **one run**, and prefer `--no-provision` against an already-built `runs/.venv-cache/*` venv when
  iterating offline.
- **Grader outputs are schema-constrained.** Student and Reviewer must request OpenAI
  `response_format={"type": "json_schema", ...}` via `LLMClient.complete(...)`; keep
  the parsers lenient only as a fallback for non-structured providers (Ollama omits the
  parameter). Do not go back to "prose plus final fenced JSON" as the primary contract —
  malformed critic JSON burns paid runs.
- **Git: agent may commit, push, and open PRs autonomously.** When a unit of work is complete and
  green, go ahead and commit, push, and open a PR without waiting for an explicit ask. Guardrails
  still hold: conventional-commit messages, **no attribution trailer** (repo convention), always work
  on a feature branch + PR, **never commit straight to `master`**, and never push until the three CI
  gates are green locally. Force-push or history rewrites on shared branches still need a heads-up.
  Standing best-practice steps (always do these, not just when asked):
  - **Name the branch for the work**, not the ticket-of-the-moment. If scope shifts so the branch
    name no longer fits, move the commits to a correctly-named branch before opening the PR.
  - **After opening a PR, confirm CI without blocking the turn.** A PR isn't "done" until remote CI is
    green — but do NOT wait on it with a blocking `gh ... --watch` or an `until/sleep` loop: the harness
    auto-backgrounds long foreground commands, which ends the turn abruptly and looks like a hang.
    Instead: do a quick one-shot check (`gh pr checks <n>` / `gh run list`) and report; if CI is still
    running, either hand back with "CI is running, I'll confirm when it lands," or run the watch with
    `run_in_background: true` AND say so up front. Same rule for the full test suite (5–8 min): run it
    `run_in_background: true` with an explicit "running, will report on completion" note — never as a
    silent blocking call. If a check goes red, fix it and push before handing back.
  - **After a PR merges, delete its feature branch** (local + remote:
    `git branch -d <b> && git push origin --delete <b>`) so stale/merged branches don't accumulate.
  - Use the `gh` CLI for PRs/checks (installed + authenticated on this machine).
- **Reviewer-on-diff per phase**, findings addressed before close-out (cost-bounded: once per phase,
  on the diff only).
- **Documentation — know which doc owns what, and update it in the same change.** Every doc has one
  job so there is one place to change, not three that drift:
  - **Dynamic — update at the end of each unit of work:**
    - `TODO.md` — the cold-start brief AND the roadmap/backlog: current status, what's shipped,
      what's in flight, what's next, cost findings, open design questions. This is the single
      source of truth for project state; read it first when resuming. (There is intentionally no
      separate `HANDOVER.md`.)
    - `README.md` — user-facing; when a user-facing capability changes (new command, new run output,
      new honesty guarantee), update it in the same change. It drifts fastest — nobody is forced to touch it.
  - **Append-only — add, don't rewrite:** `docs/architecture/NN-*.md` are dated design snapshots. When
    building something new, add a new numbered `.md` (an ecc `/plan` run usually creates one); when a
    feature ships, flip its doc's status to IMPLEMENTED but leave the design body intact.
  - **Durable — edit only when the thing it describes changes:** this file (conventions,
    architecture orientation), the templates. No routine per-work-unit updates — see "Resuming
    work in a new session" below for why this file deliberately holds no state.

## Resuming work in a new session

This file is conventions + architecture orientation only. It deliberately does not track current
status, in-flight branches, or what's next — that kind of detail goes stale within days, and a
second copy of it here just drifts from the real one. To catch up on actual project state:

1. **`TODO.md`** — start here. Current status, what's shipped, what's in flight, what's next, cost
   findings, open design questions.
2. **`docs/architecture/`** — one dated design doc per feature (`NN-*.md`), each reporting its own
   status inline (e.g. IMPLEMENTED / scoped, ready to implement / designed, not built). The
   highest-numbered files are usually the most recent work.
3. **`git log --oneline -20`, `git status`, `gh pr list`** — ground the above against what's
   actually merged vs. still on a branch or open PR. Docs and branches can lag or lead each other;
   don't assume either is current without checking. (See also "The working tree silently flips to
   `master`" under Gotchas.)

## Extending the system (common tasks)

Folded from the retired `DEVELOPMENT.md`; kept current here.

- **Add an agentic stage:** create `forged/pipeline/agents/<stage>.py` (thin `Agent` subclass) +
  `personas/<stage>.md`; wire a node/edge in `forged/pipeline/graph.py` and, if it needs routing,
  `router.py`/`failure.py`; add the stage to the relevant `config/pipeline.*.yaml`; add tests for
  routing + artifacts + prompt inputs. Behavior lives in the persona, not the wrapper.
- **Add a `LearnerProfile`/`TopicSpecification` field:** add it to the dataclass in `forged/models.py`;
  surface it in the shared context via `build_context_block` in `forged/context.py` (there is no
  `prompts.py`/`to_prompt_context` — context is one rendered block every agent reads); update
  `templates/examples/*.yaml` + `templates/README.md`; update `_default_*` in `forged/cli.py`.
- **Add a CLI command:** add a subparser in `_build_parser()` and a dispatch line in `main()` (each
  command is a `_cmd_<name>` in `forged/cli.py`); mirror an existing command's load/error-code block
  (`EXIT_OK`/`EXIT_RUNTIME`/`EXIT_USAGE`); verify `python -m forged.cli <cmd> --help`; add CLI tests.

## Gotchas learned the hard way

- **The working tree silently flips to `master`** between sessions/IDE actions; files then look
  "reverted." It's just the branch — `git switch <feature>` restores everything. Check the branch
  before debugging "lost" changes.
- **`runs/` is gitignored** — run artifacts (and any venvs/grade reports written there) won't show in
  `git status`. Don't expect them in commits.
- **A `<stamp>_course_<slug>/` run dir just means the plan had multiple modules.** A 1-module `learn`
  run gets `{stamp}_{module-title-slug}` instead. (Historically this was ambiguous because `course`
  and `learn` named their output identically; with one command it now only tells you the plan's
  shape.) Check `pipeline.log` for what actually happened.
- **Provisioning has a hardcoded 600s install timeout** (`provisioning.py`, no override yet). A cold
  `torch` build can exceed it on a slow link. Workarounds: pre-warm pip's cache, or `--no-provision`
  against an existing `runs/.venv-cache/*` venv. (Making the timeout configurable is a known nice-to-have.)
- **The planner's `requirements` block is LLM-non-deterministic**, so its content hash changes between
  runs and the venv cache rarely hits across "the same" topic. pip's wheel cache still helps if warm.
- **Git push over SSH has no key in the agent shell.** Push via `gh auth setup-git` + an explicit
  HTTPS remote URL (`git push https://github.com/<org>/<repo>.git <branch>`) rather than assuming the
  SSH remote works.
