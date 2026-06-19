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
- **Git: the user controls git.** Do **not** commit or push unless explicitly asked. Suggest the user to commit/PR, when you think its usefull. When asked:
  conventional-commit messages, **no attribution trailer** (repo convention), feature branch + PR,
  never commit straight to `master`.
- **Reviewer-on-diff per phase**, findings addressed before close-out (cost-bounded: once per phase,
  on the diff only).
- **Documentation:** always update the documents used, especially when things change. When building new stuff, always add a .md in the docs/archtiecture/ folder with the given structure. Most of the time there will be a .md created when the ecc "plan" command is used to plan new features and integrations.

## Current state & next task

- **Merged (PR #5):** the Reviewer second critic, learner-aligned explanation personas, and
  runnable-kernel packaging. `master` reflects this; pipeline docs are synced.
- **🔜 Top open task — R1 (topic fidelity).** The agentic loop can **silently drop a capability the
  `--topic` explicitly requested** (it shipped a "setup local LLMs" notebook for a "setup *and train*"
  topic). Full spec + start-here pointer: **`docs/architecture/10-output-quality-remediation.md` →
  Part IX / R1** (also promoted into that doc's "read this first" hand-off). Start with the
  Student/Reviewer scope rubric in `personas/student.md` + `personas/reviewer.md`.
- **Roadmap & priorities:** `TODO.md` (Step 7 input-spec testing is postponed behind R1; Phase 2 =
  curriculum planner).

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
