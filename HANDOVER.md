# HANDOVER — next session start here

_As of 2026-07-04. Cold-start brief: read this + the files it names and you have full context.
When this session's work is superseded, update or delete this file._

## TL;DR

Since the last handover (2026-06-26, token observability), three more things merged: **structured
(JSON-schema) grader outputs** (`docs/architecture/15-structured-grader-output.md`), **code maps +
cell briefs + planner readiness verdict** (`docs/architecture/14-code-explanation-and-readiness.md`,
Parts I–II), and a README/DEVELOPMENT docs refresh (PR #15). `CLAUDE.md`, `TODO.md`, and this file had
drifted out of sync with that merged work — reconciling them was this session's first task (you're
reading the result).

The project now has an **open fork with no decision made yet**: curriculum planner Phases 3–5, or
doc 14's Part III (escalation workflow). Both are unblocked. Pick one before writing code — see
`TODO.md` → "Next Up" for the full tradeoff writeup.

## ▶ Do this first

1. **The fork is decided (2026-07-05): build the Smart Front Door.** Design + granular task list:
   `docs/architecture/16-smart-front-door.md` (one `forged learn` command; unconditional confirmation
   gate; natural-language plan adjustments → deterministic CourseSpec ops; Tier-2 guided re-plan).
   Branch: `feat/smart-front-door`. Tasks are sized for cheaper models — implement them in order
   (Phase 1: pure operations first), TDD, suite green after every task.
2. Still owed regardless: the **cli deliverable-writer cleanup** (extract `_write_agentic_summary` /
   `_write_final_notebook` / `_write_learner_package` out of `cli` into a shared module) and a
   **paid live full-course run** (smoke-test with `--max-modules 1` first).

## Process note from this session

Two commits (`e6b778d` "fix: enforce structured grader outputs", `dfb1ce3` "docs: document structured
grader outputs") landed **directly on `master`**, not through a feature branch + PR. That breaks the
repo's own stated convention (never commit straight to `master`). Left as-is — low blast radius (a
grader-output hardening fix + docs) — but don't repeat the pattern; route even small follow-up fixes
through a branch/PR.

## Current state

See `CLAUDE.md` → "Current state & next task" for the durable version. Summary:

- **Merged:** Reviewer second critic (PR #5), R1 topic fidelity (doc 11), orientation cell (doc 12),
  curriculum planner Phases 1–2 (doc 13), token observability (PR #13), code maps + readiness verdict
  (doc 14, Parts I–II), structured grader outputs (doc 15).
- **Not merged:** curriculum Phases 3–5, doc 14 Part III, the cli deliverable-writer cleanup, the paid
  full-course run.

## Gotchas

See `CLAUDE.md` → "Gotchas learned the hard way": the working tree silently flips to `master` between
sessions, `runs/` is gitignored, provisioning has a hardcoded 600s install timeout, the planner's
`requirements` block is LLM-non-deterministic (venv cache rarely hits), and git push over SSH has no
key in the agent shell (use `gh auth setup-git` + an explicit HTTPS remote URL).
