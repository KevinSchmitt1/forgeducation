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
    deterministic classifier/router that **merges both critics' findings** — and, since doc 22's
    R5, their **goal-fit verdicts** — before `classify()`.
    **ContentReviser** is the LLM that rewrites prose for the `CONTENT_QUALITY` route.
  - **Acceptance is not an average** (doc 22, R1/R5). `quality_score` is the mean of five rubric
    dimensions, but a mean can hide a fatal one, so `classify()` also reads: any single dimension
    below `FATAL_DIMENSION_FLOOR`, and the critics' `goal_fit` verdict ("does this code earn its
    place?" — `drifted` / `overwhelming` / `insufficient`). Only the Reviewer may report `drifted`,
    because that is the one verdict that routes to the planner and a replan can amputate.
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
- `forged/service.py` — the UI's only door into the backend: `plan` / `preview` / `edit` / `adjust` /
  `build` step functions over the CLI + curriculum code (no forked pipeline logic). `build` runs the
  CLI's own `_build_confirmed` in a child process (`python -m forged.service build --request …`).
- `forged/ui/` — the local BYOK web front door (doc 25): `front_door.py` holds **all** UI behaviour
  as gradio-free pure steps `(frozen Session, widget values) → (Session, View)`; `app.py` is Gradio
  wiring only; `fake_llm.py` is the canned offline LLM behind `--fake-llm`
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

### The web UI (`forged ui`) — running and testing it

```bash
.venv/bin/pip install -e '.[dev,ui,e2e]'          # dev already pulls in ui (so CI tests the UI layer)
.venv/bin/python -m playwright install chromium  # once; the browser for the e2e
.venv/bin/python -m forged.cli ui --fake-llm     # offline demo → http://127.0.0.1:7860
.venv/bin/python -m forged.cli ui                # real mode: paste a key in the page (planner calls bill!)

.venv/bin/python -m pytest tests/test_service.py tests/ui -q                   # units + wiring (~15s)
FORGED_E2E_SCREENSHOTS=tests/ui/screenshots \
  .venv/bin/python -m pytest tests/ui/test_browser_e2e.py -q                     # real-browser e2e
```

- **`--fake-llm` is the only safe way to exercise the UI** without spending: planner, readiness and
  adjuster calls get canned answers, and **Launch is a dry run** (`DryRunLauncher` writes
  `ui_request.json` + `ui_launch.log`, spawns nothing). Real mode's *Plan* button makes a paid
  gpt-5-mini call and *Launch* starts a full paid build — both need the user's consent.
- **The e2e is the UI's vertical rung** (see "Lane workflow"). It starts `python -m forged.cli ui
  --fake-llm` as a child process with no key in its env and drives Chromium through
  validation → inputs → plan → edits → re-plan → undo → confirm → launch. It **skips** when
  Playwright or a browser is missing, so it is silently skipped in CI — run it locally before
  claiming a UI change works. Stable selectors are the `fd-*` `elem_id`s in `app.py`.
- **Put UI behaviour in `front_door.py`, not `app.py`** — it is unit-tested without a browser;
  `app.py` lambdas only run inside a served app and are not seen by coverage.
- **BYOK is a tested contract:** the key is a widget value (never `Session` state), scoped to
  in-process planner calls and handed to the build only via env. Tests assert it never reaches disk,
  logs, the page text, or `repr(Session)`; keep those assertions when touching the key path.
- **Docker:** `docker build -t forgeducation . && docker run --rm -p 127.0.0.1:7860:7860 -v
  "$PWD/runs:/app/runs" forgeducation`. The image installs editable on purpose — see the gotcha below.

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
  **Merging is the user's call** — at the CP2 checkpoint (see "Human checkpoints" below), never on
  CI alone and never without their explicit word.
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

## Lane workflow (how-to for agents)

Work is split into independent slices ("lanes"). Each lane is a **branch in this repo** with a
tracked brief in **`docs/lanes/`**. **Everything lives in this one repository** — no sibling
folders (parallel-lane worktrees go under the repo's gitignored `.worktrees/`, see below).
`docs/lanes/README.md` is the live index; each `docs/lanes/NN-*.md` owns one lane's scope,
file-ownership (collision map), human checkpoints, and definition of done. New briefs start from
`docs/lanes/TEMPLATE.md`.

**To start a lane:**

```bash
git checkout master && git pull
git checkout -b <lane-branch>      # branch name is in the lane's brief
# then: read docs/lanes/NN-*.md and work
```

**To resume a lane in a fresh session**, tell the agent e.g. *"continue lane 2 per
`docs/lanes/02-local-observability.md`"*. It runs `git checkout <lane-branch>` (creating it from
master if it doesn't exist yet), reads the brief, and picks up from `git log` + the brief's
**Status** line. Then:

- **Stay inside your file-ownership map.** The point of lanes is no merge conflicts — if your brief
  says "do not touch `router.py`/`personas/`", don't. Lanes that share a hot file (`router.py`,
  `failure.py`, `classify()`, `personas/`, `graph.py`, `mode.py`) **cannot** both be in flight — one
  serializes after the other. The brief states this per lane.
- **One lane at a time in the working tree.** This repo has a single working tree, so only one lane's
  branch is checked out at once — finish, commit, or stash before switching. (Two lanes *truly*
  simultaneously is the one case for `git worktree`, but the default here is branch-switching.)
- **Parallel lanes → worktrees live inside the repo, under the gitignored `.worktrees/`** — never in
  a sibling folder next to the repo. A worktree exists only while its lane runs in parallel with
  another; once the lane's PR merges, remove it (the work is in git — nothing is lost):

  ```bash
  scripts/start_lane.sh <NN>          # worktree under .worktrees/ + Claude in tmux window laneNN
  git worktree remove .worktrees/<lane-slug> && git branch -D <lane-branch>  # after merge
  ```

  `start_lane.sh` reads the branch from the brief, creates (or resumes) the worktree from `master`,
  and opens a tmux window whose agent starts at CP0. `--dry-run` prints what it would do.

  Run commands from the worktree's own root so `forged` imports resolve to that checkout (the
  editable install follows the cwd) — the shared `.venv` by absolute path is fine. A lane that adds
  dependencies gets its own `.venv` inside its worktree rather than mutating the shared one. While lanes run in parallel, only the coordinating
  session edits `TODO.md` and `docs/lanes/README.md`.
- **Use the project `.venv`** (`.venv/bin/python`, `.venv/bin/ruff`, …) — it's already installed; no
  per-lane venv bootstrap.
- **Verify before merge — by deliverable, not by lane number** (rungs: green → exercised → validated,
  see "Verification discipline"). CI gates are necessary but **horizontal**; they are not this check:
  - **Design/decision docs** (deliverable is a `docs/…` file): no runtime → validated by *review*.
  - **Code that changes runtime behavior:** at least *exercised* — run the affected path, not just
    mocked tests.
  - **A UI implementation:** driven in a **real browser (e2e / Playwright)** — the most
    vertical-hungry deliverable, not the least.
  - **LLM-judgement changes** (critics, router, personas, graders): run the **Lane 1 live-replay
    harness** before merge; that is their vertical rung.
- **Sync + finish:** `git rebase master` (or merge) so the branch carries the latest shared state,
  run the three CI gates (ruff / mypy / pytest ≥80%), and open a PR per the git conventions above.
  When the PR merges, delete the branch (local + remote).

Lane briefs are coordination docs, not project state — **`TODO.md` remains the single source of truth**
for status, dependencies between lanes, and what's held back (e.g. R6/R7 and the author-split
*implementation*, which serialize because they share hot files).

### Human checkpoints (every lane — added 2026-09-29)

PR review alone was not enough human-in-the-loop: by the time a PR exists, every decision in it has
been made. So every lane **stops and waits** at planned checkpoints. A brief may add checkpoints but
not drop them; the one exception is CP1 for a docs-only lane (nothing to demo — say so in the brief).

| | When | The packet the agent posts | The user answers |
|---|---|---|---|
| **CP0 kickoff** | after reading the brief, **before any code** | its understanding in ≤3 lines · the plan (steps, files) · each real choice with a recommendation · open questions · what CP1 will demo | go / adjust |
| **CP1 demo** | once the core works, **before polish, tests-to-80% and the PR** | copy-paste commands to try it hands-on (free: fake LLM, no key) · what to look at · known rough edges | looks right / change X |
| **CP2 merge** | PR opened, CI green | the review packet: what changed in plain words · 3 things worth checking (`file:line`) · how to try it · confidence level (green / exercised / validated) · what's not done · decisions and follow-ups for the user. The PR body carries the same packet. | merge / send back |
| **SPEND** | before **any** billable call (live-replay, paid run) | what call, estimated cost, why now. One approval covers one run — never implied, never reused. | yes / no |

**Mechanics** — the same for every lane, so the user has one place to look:

1. Post: `python scripts/checkpoint.py post --lane NN --cp CP0 --summary "<what you need>" < packet.md`
   (or `--body`). It appends to the single, gitignored **`INBOX.md` in the main checkout** — the
   same file from any worktree — and pops a macOS notification.
2. **End the turn.** Do not continue past a checkpoint in the same turn, and do not treat silence
   as approval.
3. When the user answers (in the lane's tmux window): add one line to the brief's **Checkpoint
   log** (date · CP · decision), run `python scripts/checkpoint.py resolve --lane NN --cp CP0
   --note "<decision>"`, and continue.

The user sees what is waiting with `python scripts/checkpoint.py list` (or by opening `INBOX.md`).
The coordinating session watches the inbox too, and relays or summarizes packets on request.

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
   don't assume either is current without checking. (See also "The working tree ...)

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

- **The working tree is changed when the person who is in charge merges and switches to `master`**; check first before trying to change anything.
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
- **A wheel (non-editable) install cannot find `personas/` or `config/`.** They live at the repo root,
  outside the `forged` package, and `cli.PACKAGE_ROOT` looks next to it. Editable installs work; the
  Dockerfile installs editable for this reason. Fixing it properly is its own lane (it moves
  `personas/`, a hot directory).
- **`python -m ipykernel install --user --name python3` rewrites the machine-wide kernel.** In a
  worktree it points every checkout's `python3` kernel at *that* worktree's venv. Don't run it from a
  worktree; the main checkout's venv owns the user kernel.
- **Git push over SSH has no key in the agent shell.** Push via `gh auth setup-git` + an explicit
  HTTPS remote URL (`git push https://github.com/<org>/<repo>.git <branch>`) rather than assuming the
  SSH remote works.
