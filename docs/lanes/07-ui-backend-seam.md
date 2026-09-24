# Lane 7 — UI backend seam (`course_from_dict` + gate-as-step-function) (CODE, additive)

**Branch:** `feat/ui-backend-seam` · **Type:** code, additive · **Depends on:** none
**Status:** not started.
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `docs/architecture/25-*.md`
("First-implementer plan" + "Why the backend is more ready than it looks") and
`docs/architecture/19-*.md` (identifies the `course_from_dict` gap) first.

## Why this lane exists
Doc 25 decided: **BUILD a scoped local BYOK/Docker input front door.** Its load-bearing finding
is that the frontend is the bulk of the work but the **backend seam is small, additive, and
de-risks the whole idea** — and is independently useful (any future automation / second entry
point wants the same two-phase library API). This lane builds **only that seam**, not the UI.
It is deliberately **parallel-safe** with Lane 6 (it touches none of the hot pipeline files).

## Scope
1. **`course_from_dict`** — the inverse of `course_to_dict` in `forged/curriculum/model.py`
   (the forward direction exists; the inverse does not — doc 19 flagged this exact gap). Add it
   with a **round-trip test** (`course_to_dict(course_from_dict(d)) == d` and object-equality the
   other way). Needed so a plan can round-trip UI ↔ backend as JSON.
2. **Gate as a step function** — extract `apply_adjustment(course, instruction) -> new_course`
   from the stdin loop in `run_gate` (`forged/curriculum/`), so the deterministic `PlanAdjuster`
   ops (`merge / drop / force_single / reorder / confirm / cancel`) are callable **without owning
   the I/O**. `run_gate`'s existing loop should then call this same function — no behavioural
   change to the CLI gate, just a callable seam beneath it.
3. **(Optional, only after 1–2) a thin service wrapper** sketch: `plan(inputs) -> plan-dict`,
   `apply_adjustment(plan, instruction) -> plan`, `build(plan, inputs) -> run_dir`. Keep it a thin
   library layer; **do not** build the Gradio/Streamlit app here (that is the next lane).

## Files you own (collision map)
- `forged/curriculum/model.py` (`course_from_dict`), `forged/curriculum/gate.py` /
  `adjuster.py` (extract `apply_adjustment`; keep `run_gate` calling it), plus this lane's tests.
- **Additive only. Do NOT touch** `router.py`, `failure.py`, `classify()`, `reviser.py`,
  `personas/`, `graph.py`, `mode.py` — those are Lane 6's / the author-split's. This keeps the two
  active lanes collision-free.
- **BYOK note (design only here):** the eventual service injects the user's key per-process into
  `forged/llm.py`'s env read, never persisted / logged / traced. Don't build key handling in this
  lane; just don't foreclose it.

## Constraints (beyond the shared ones in CLAUDE.md)
- **Immutability:** `course_from_dict` returns a frozen `CourseSpec`; `apply_adjustment` returns a
  **new** course, never mutates its input.
- **No CLI regression:** `run_gate`'s observable behaviour is byte-identical; the extraction is
  refactor-under-test.

## Verification (by deliverable — runtime code → exercised)
- Round-trip unit test for `course_from_dict` (and that it round-trips a real multi-module plan
  from `--plan-only`, e.g. a saved `course_plan.json`).
- Unit tests for `apply_adjustment` covering each op; a test that `run_gate` still drives the same
  edits through the extracted function.
- **Exercise it:** run `forged learn --plan-only` and confirm the plan JSON round-trips through
  `course_from_dict` unchanged — the vertical rung for this deliverable (no paid call needed).
- All three CI gates green (ruff / mypy / pytest ≥80%).

## Done means
`course_from_dict` exists + round-trips (tested and exercised on a real plan); `apply_adjustment`
is a callable, immutable step function that `run_gate` uses; no hot-file touches; PR opened.
