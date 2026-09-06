# Lane 3 — Author-identity split (DESIGN DOC ONLY)

**Branch:** `docs/author-split-design` · **Type:** design doc, no code · **Depends on:** none
**Status:** not started.
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `docs/architecture/17-*.md`
(lesson modes) and `docs/architecture/22-*.md` first.

## The problem to design a fix for (Kevin's framing)
There is **one `code_author`** agent/node that runs regardless of lesson mode. For an `artifact`
lesson (cells build+validate a file/config/scaffold — e.g. a network config, a Linux setup) or a
`conceptual` lesson (prose, nothing runs), "author some code" is the **wrong job description**. Plan:
**split the `code_author` identity from the artifact/conceptual author.**

## Deliverable
`docs/architecture/23-author-identity-split.md` (append-only; next number after 22). Status:
"designed, ready to implement." Must cover:

1. **The split** — `code_author` (executable, compute-and-show) vs a new `artifact_author`
   (artifact + conceptual: *build-and-validate an artifact* / *explain*). Two personas or one
   mode-parameterized persona? Recommend one, with reasoning.
2. **Every downstream part that moves with it** — trace each concretely:
   - `forged/pipeline/graph.py` — single author node becomes mode-dispatched.
   - `personas/` — new persona file(s).
   - `config/pipeline.*.yaml` — new stage → model entry (gpt-5 tier).
   - `forged/pipeline/router.py` + `failure.py` — the `code`-scope / `content_reviser` **return edges
     must route back to whichever author produced the notebook**, not always `code_author`.
   - `forged/executor.py` — already no-ops conceptual / validates artifact (doc 17); confirm alignment.
   - reviser + `classify()` — already mode-aware; confirm the split preserves mode threading.
3. **Test plan** — routing per mode, persona-input assertions, no-regression on executable.
4. **CRITICAL sequencing** — this **collides with R6/R7** (both edit `personas/`, `graph.py`,
   `router.py`). State that *implementation* serializes after the R6/R7 lane; design completes now.

## Done means
The design doc exists, covers all six touch-points, and flags the R6/R7 serialization. Open a PR.
