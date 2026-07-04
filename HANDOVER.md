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

1. **Decide the fork** (curriculum Phases 3–5 vs. doc 14 Part III) — see `TODO.md` for both options
   spelled out. Doc 14 Part III is arguably the higher-leverage pick: it's the consumer of both R1 and
   curriculum Phases 1–2, and doc 14 explicitly calls it "the next feature."
2. Whichever is picked, open with a `/plan` phase before coding.
3. Regardless of pick: the **cli deliverable-writer cleanup** (extract `_write_agentic_summary` /
   `_write_final_notebook` / `_write_learner_package` out of `cli` into a shared module) is still owed,
   and a **paid live full-course run** is still unspent (smoke-test with `--max-modules 1` first).

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
