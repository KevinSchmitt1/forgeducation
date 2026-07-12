# CLAUDE.md — working notes for agents in this repo

forgeducation is a multi-agent CLI that turns a one-line topic into a **runnable, self-checked**
teaching notebook. The defining idea: one stage **actually executes** the generated notebook and
captures what every cell really does, so explanations are checked against reality, not assumption.

This file is repo-specific orientation + the conventions that aren't obvious from the code. General
coding/testing/git style is assumed (see your global rules); this covers what's particular to here.

#EDIT:
This section above is outdated. We want to get to something where there are no differences in the cli calls anymore. So there is only on cli call of the forgeducation program, the workflow decides what flow to use, depending on the complexity and coverage of the topic.

## Architecture at a glance

Two execution paths share the same agents, personas, and context block:

- **Agentic** (`forged agentic`, the one we ship) — a LangGraph pipeline that classifies failures
  and reroutes. Flow:
  `planner → code_author → executor → student → reviewer → revisor → (content_reviser | replan | END)`
  - **Two critics** run before the deterministic router: **Student** (learner POV — "could I follow
    this?") and **Reviewer** (expert correctness/quality). The **Reviser** is *not* a critic — it's a
    deterministic classifier/router that **merges both critics' findings** before `classify()`.
    **ContentReviser** is the LLM that rewrites prose for the `CONTENT_QUALITY` route.
  - Routing is deterministic (`router.py` + `failure.py`); a finding's **scope** (`plan`/`structure`/
    `code`/`content`) decides where it's sent. Scope tagging matters a lot — see R1 below.
- **Linear** (`forged build`) — fixed single pass; still uses `reviewer.md` as a critic. We don't
  actively develop it; don't "fix" its docs as part of agentic work. This is not used anymore.

Agents are thin Python wrappers; their behavior lives in **`personas/*.md`** (planner, code_author,
student, reviewer, reviser). Most quality/pedagogy changes are persona edits, not code.

The executor **provisions a per-run venv** from the planner's `requirements` block (content-addressed
cache under `runs/.venv-cache/`), registers a kernel, and runs the notebook in it. `--no-provision`
skips that and runs in the base `python3` kernel.

### Where things live
- `forged/pipeline/` — agents, graph, state, router, failure classification, provisioning hook
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
    - `CLAUDE.md` → "Current state & next task" — the cold-start brief (what's merged, what's on the
      branch, what's next). This is the single source of truth for project state; read it first when
      resuming. (There is intentionally no separate `HANDOVER.md`.)
    - `TODO.md` — the roadmap/backlog across features, cost findings, open design questions.
    - `README.md` — user-facing; when a user-facing capability changes (new command, new run output,
      new honesty guarantee), update it in the same change. It drifts fastest — nobody is forced to touch it.
  - **Append-only — add, don't rewrite:** `docs/architecture/NN-*.md` are dated design snapshots. When
    building something new, add a new numbered `.md` (an ecc `/plan` run usually creates one); when a
    feature ships, flip its doc's status to IMPLEMENTED but leave the design body intact.
  - **Durable — edit only when the thing it describes changes:** this file (conventions), the
    templates. No routine per-work-unit updates.

## Current state & next task

- **Merged & on `master`:** the Reviewer second critic + learner-aligned personas (PR #5);
  **R1 — topic fidelity, Half A** (`docs/architecture/11-…`); the **learner orientation cell**
  (`docs/architecture/12-…`); the **curriculum planner Half B, Phases 1–2** (`docs/architecture/13-…`)
  — plan a course (`forged course --plan-only`) and run it (`forged course`, orchestrating one lesson
  pipeline per module with the prior-knowledge context hand-down); **per-call token observability**
  (`usage.json`/`USAGE.md`, PR #13); **code maps, cell briefs, and the planner readiness verdict**
  (`docs/architecture/14-…`, Parts I–II, PR #14); and **structured (JSON-schema) grader outputs** for
  Student/Reviewer (`docs/architecture/15-…`, PR #15 + follow-up hardening). The four honesty features
  compound: R1 (don't drop in a lesson) → orientation (don't silently assume a prereq) → curriculum
  (don't drop/re-teach across a course) → readiness (don't cram a topic past the learner's foundation).
- **On `feat/smart-front-door` (2026-07-07):** the **Smart Front Door** (`docs/architecture/16-…`,
  Phases 1–5) — one `forged learn` command that sizes single-lesson vs. course, shows the plan + a
  rough cost/time estimate, and runs nothing paid until the learner confirms; plan tweaks classified
  into deterministic `CourseSpec` ops (merge/drop/force_single/reorder) with a guided gpt-5-mini
  re-plan as the only escalation. Adds a fifth honesty feature: **don't spend before you agree.**
- **On `feat/curriculum-reactive-loop` (2026-07-12):** **Curriculum planner Phase 4 — the reactive
  safety net** (`docs/architecture/13-…` Phase 4). `forged/curriculum/reactive.py::run_course_reactive`,
  opt-in behind `--redecompose` (+ `--max-depth`, default 1) on `course` and `learn`: a module that
  still drops a capability hands the overflow back to the CurriculumPlanner as a new module, run and
  appended to the grown course; bounded by `--max-modules` (total budget) and `--max-depth` (rounds).
  The orchestrator's per-module hand-down was extracted to `run_module_with_handdown` so both paths
  seed context identically. Shipped ahead of Phase 3 (it needs no assembler). This completes the R1
  → planner → R1 self-correcting loop.
- **🔜 Next:**
  1. **Curriculum planner Phases 3 & 5** — course assembly (`assembler.py`: index + cross-links +
     aggregate `COURSE.md` that also records each reactive re-split) and close-out. Phase 4 is now done.
     Start: `docs/architecture/13-curriculum-planner.md`.
  2. **Doc 14 Part III — escalation workflow.** Wire the readiness verdict so the planner detecting
     "gap too deep" auto-routes into the front door's course path. The front door supersedes Part III's
     gate sketch; what remains is the auto-route on the verdict. Start:
     `docs/architecture/14-code-explanation-and-readiness.md` Part III.

  The **cli deliverable-writer cleanup** is now **done** (`write_agentic_summary`/
  `write_final_notebook`/`write_learner_package` live in `forged/deliverables.py`; both the single-lesson
  CLI path and the curriculum orchestrator import them there, so the orchestrator's deferred `forged.cli`
  import is gone). Still owed regardless: a **paid live `forged learn` run** (1-module smoke test first).
- **Roadmap & priorities:** `TODO.md`.

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
- **Provisioning has a hardcoded 600s install timeout** (`provisioning.py`, no override yet). A cold
  `torch` build can exceed it on a slow link. Workarounds: pre-warm pip's cache, or `--no-provision`
  against an existing `runs/.venv-cache/*` venv. (Making the timeout configurable is a known nice-to-have.)
- **The planner's `requirements` block is LLM-non-deterministic**, so its content hash changes between
  runs and the venv cache rarely hits across "the same" topic. pip's wheel cache still helps if warm.
- **Git push over SSH has no key in the agent shell.** Push via `gh auth setup-git` + an explicit
  HTTPS remote URL (`git push https://github.com/<org>/<repo>.git <branch>`) rather than assuming the
  SSH remote works.
