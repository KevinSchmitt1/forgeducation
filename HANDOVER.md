# HANDOVER — next session start here

_As of 2026-07-07. Cold-start brief: read this + the files it names and you have full context.
When this session's work is superseded, update or delete this file._

## TL;DR

The **Smart Front Door (doc 16) is implemented** on `feat/smart-front-door` — Phases 1–5, one
commit per phase, TDD, all three CI gates green locally. One new command, `forged learn`: it sizes
the topic (single lesson vs. course) with the CurriculumPlanner, shows the plan + a rough cost/time
estimate, and **runs nothing paid until the learner confirms**. Plan tweaks in plain language
("make it one notebook", "combine 1 and 2", "drop module 3") are classified by a small model and
applied as deterministic `CourseSpec` operations — no expensive re-plan for a structural tweak;
non-structural feedback escalates to exactly one guided gpt-5-mini re-plan.

A PR is open (or about to be — see git log / `gh pr list`). Once it merges, delete the branch.

## ▶ Do this first

1. **Confirm the PR merged and CI is green**, then delete `feat/smart-front-door` (local + remote).
2. **Owed follow-ups for the front door** (not blocking merge, but the honest next steps):
   - **Paid live smoke run** of `forged learn`: a 1-module topic to exercise the real gate →
     single-lesson path, then a small (2-module) course. Needs user consent + cost. This is the only
     part of doc 16 not yet exercised against real models.
   - **Deliverable-writer extraction** (long-standing cleanup): move `_write_agentic_summary` /
     `_write_final_notebook` / `_write_learner_package` out of `cli.py` into a shared module. The
     front door already extracted `_run_agentic_lesson` from `_cmd_agentic` (partial down-payment).
3. **Then the queued fork:** curriculum planner Phases 3–5 (course assembly + reactive
   `R1 → planner → R1` re-decomposition). Start: `docs/architecture/13-curriculum-planner.md`,
   and `TODO.md` → "Next Up".

## What shipped this session (doc 16)

| Phase | Code | Tests |
|---|---|---|
| 1 | `forged/curriculum/operations.py` — merge/drop/force_single/reorder (pure) | `tests/test_curriculum_operations.py` (23) |
| 2 | `forged/curriculum/adjuster.py` + `personas/plan_adjuster.md` — Tier-1 classifier | `tests/test_curriculum_adjuster.py` (20) |
| 3 | `forged/curriculum/planner.py` — structured output + `guidance=` (Tier-2) | `tests/test_curriculum_planner.py` (extended) |
| 4 | `forged/curriculum/gate.py` — `render_plan` + `run_gate` | `tests/test_curriculum_gate.py` (15) |
| 5 | `forged/cli.py` — `_cmd_learn` + `learn` subparser + `_run_agentic_lesson` extraction | `tests/test_cli_learn.py` (7) |

Design of record: `docs/architecture/16-smart-front-door.md` (now IMPLEMENTED, with an
implementation record table).

## Current state

- **Merged on `master`:** Reviewer second critic (PR #5), R1 topic fidelity (doc 11), orientation
  cell (doc 12), curriculum planner Phases 1–2 (doc 13), token observability (PR #13), code maps +
  readiness verdict (doc 14, Parts I–II), structured grader outputs (doc 15).
- **On `feat/smart-front-door` (this session):** the smart front door (doc 16, Phases 1–5).
- **Not started:** curriculum Phases 3–5, doc 14 Part III (the front door supersedes its gate
  sketch, but the auto-route-on-readiness-verdict idea is still unbuilt), the paid live front-door
  run, the deliverable-writer extraction.

## Gotchas

See `CLAUDE.md` → "Gotchas learned the hard way": the working tree silently flips to `master`
between sessions (`git switch feat/smart-front-door` to restore), `runs/` is gitignored,
provisioning has a hardcoded 600s install timeout, the planner's `requirements` block is
LLM-non-deterministic (venv cache rarely hits), and git push over SSH has no key in the agent shell
(use `gh` / an explicit HTTPS remote URL).
