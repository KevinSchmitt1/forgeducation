# Lane 9 — Author-identity split: implementation (CODE + PERSONA, hot-file lane)

**Branch:** `feat/author-split` · **Type:** code + persona · **Depends on:** Lane 3 design (✅ #55,
doc 23), Lane 6 R6→R7 (✅ #60 — the serialization doc 23 Part VI required is satisfied)
**Status:** implemented on `feat/author-split`, PR open — green + exercised; live-replay + paid run owed (not validated).
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `docs/architecture/23-author-identity-split.md`
in full (recommendation **B**, the touch-point table, Part IV test plan, Part V DRY risk, Part VI) and
doc 22's "Implementation note — R6 and R7" (what the post-#60 author persona now contains) first.

## Why this lane exists
One `code_author` identity runs for every lesson mode; for `artifact` and `conceptual` lessons its
first sentence ("implement the plan's code demo") is the wrong job description. Doc 23 designed the
fix and recommended **B: two persona files, one author node** — which sidesteps the router
collision entirely. R6/R7 has now landed, so this is unblocked, and doc 23 Part VI notes landing it
after R7 is also the DRY-cheaper order.

## Scope (doc 23, recommendation B — implement as designed)
1. `personas/artifact_author.md` (**new**) — the Artifact Author identity for `artifact` +
   `conceptual` modes; the shared machinery (orientation, pipeline contract, patch protocol, the
   R6/R7 digest/remake sections) stays **verbatim-identical** to `personas/code_author.md`.
2. Mode-dispatched persona selection in the single author agent (`forged/pipeline/agents/…`),
   keyed on the lesson mode the pipeline already carries. `executable` → `code_author.md`, byte-
   identical behaviour (the default path must not move).
3. Strip the now-redundant mode branches out of `code_author.md` only as doc 23 prescribes.
4. If doc 23 calls for a config/stage entry, add it; if it says a touch-point does **not** move
   under B (graph, router, failure, executor, classify), **do not move it**. If implementation
   reveals doc 23 was wrong about a touch-point, stop and write it down in the PR rather than
   widening scope silently.

## Files you own (collision map)
- `personas/code_author.md`, `personas/artifact_author.md`, the author agent file under
  `forged/pipeline/agents/`, `config/pipeline.*.yaml` only if doc 23 requires it, this lane's tests,
  and an "Implementation note" appended to doc 23 (append-only; flip its status to IMPLEMENTED).
- **Do NOT touch** `forged/cli.py`, `forged/service.py`, `forged/ui/`, `pyproject.toml`,
  `Dockerfile`, `README.md` UI section — Lane 8 is in flight there.
- **Do NOT edit** `TODO.md` or `docs/lanes/README.md` — the coordinator owns those while two lanes
  run in parallel. Update only this brief's **Status** line.

## Constraints
- **No paid/network LLM calls.** The Lane 1 live-replay (`pytest -m live`, needs `OPENAI_API_KEY`)
  is this lane's vertical rung, but it bills — do **not** run it; list it in the PR as owed.
- TDD; immutability; persona changes are the behaviour, the Python wrapper stays thin.

## Verification
- Doc 23 Part IV tests: persona selected per mode; executable path byte-identical prompt input
  (pin it); both persona files exist and share the verbatim common sections (a drift test that
  **can fail** — prove it by mutating a copy in the test, R1's lesson).
- Existing routing/graph tests still green with no edits to routing files.
- **Exercised:** render the actual system prompt the author receives for each of the three modes
  from a real corpus/plan fixture (no LLM call) and eyeball it in the PR description.
- Three CI gates green (ruff / mypy / pytest ≥80%). State the confidence level honestly:
  green + exercised; **not** validated (that needs live-replay + the paid run, after the UI).

## Done means
Two author identities, one node, dispatched by mode; executable unchanged and pinned; drift test
proven fail-capable; doc 23 marked IMPLEMENTED with an implementation note; PR opened with the
live-replay listed as owed.
