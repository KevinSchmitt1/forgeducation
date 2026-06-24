# CLAUDE.md — working notes for agents in this repo

forgeducation is a multi-agent CLI that turns a one-line topic into a **runnable, self-checked**
teaching notebook. The defining idea: one stage **actually executes** the generated notebook and
captures what every cell really does, so explanations are checked against reality, not assumption.

This file is repo-specific orientation + the conventions that aren't obvious from the code. General
coding/testing/git style is assumed (see your global rules); this covers what's particular to here.

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
- **Documentation:** always update the documents used, especially when things change. When building new stuff, always add a .md in the docs/archtiecture/ folder with the given structure. Most of the time there will be a .md created when the ecc "plan" command is used to plan new features and integrations.

## Current state & next task

> **Resuming? Read [`HANDOVER.md`](HANDOVER.md) first** — cold-start brief with the next task, file
> map, and open discussion items. Next session should open with a `/plan` phase.

- **Merged & on `master`:** the Reviewer second critic + learner-aligned personas (PR #5);
  **R1 — topic fidelity, Half A** (`docs/architecture/11-…`); the **learner orientation cell**
  (`docs/architecture/12-…`); and the **curriculum planner Half B, Phases 1–2**
  (`docs/architecture/13-…`) — plan a course (`forged course --plan-only`) and run it
  (`forged course`, orchestrating one lesson pipeline per module with the prior-knowledge context
  hand-down). The three honesty features compound: R1 (don't drop in a lesson) → orientation (don't
  silently assume a prereq) → curriculum (don't drop across a course; don't re-teach across modules).
- **🔜 Next — curriculum planner Phases 3–5.** Phase 3 (course assembly: index + cross-links), Phase 4
  (reactive `R1 → planner → R1` re-decomposition when a module is still over-large), Phase 5 (close-out).
  Plus a **cleanup**: extract `cli`'s per-run deliverable writers into a shared module (the orchestrator
  currently reaches into them via a deferred import). A **live full course run** is unspent (paid; do a
  `--max-modules 1` smoke test first). Start-here: `docs/architecture/13-curriculum-planner.md`.
- **Roadmap & priorities:** `TODO.md` (Step 7 input-spec testing remains postponed; curriculum Phases
  3–5 are the active track).

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
