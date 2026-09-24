# Lane 6 — R6 → R7: critique digest, then informed remake (CODE + PERSONA)

**Branch:** `feat/critique-digest-remake` · **Type:** code + persona · **Depends on:** Lane 1 (done)
**Status:** not started.
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `docs/architecture/22-*.md`
(Parts III–VI) first — this lane *implements* R6 then R7 from that doc.

## Why this lane exists (the defect is confirmed, not suspected)
Every agent reads exactly `revision_brief_v{iteration - 1}` — verified in `code_author.py`,
`planner.py`, `content_reviser.py`. So the iteration-3 rewrite knew nothing of what iterations
0–2 found. That is the mechanism behind quality going **74 → 82 → 74 → 71** on the 2026-08-13
run. R6 makes findings **accumulate**; R7 makes a remake a **recorded, informed decision**
instead of a silent re-roll.

## Scope (R6 first, then R7 — the digest must exist before a remake can use it)
1. **R6 — `critique_digest`** (`reviser.py`, code). An artifact the reviser maintains **across**
   iterations: every finding from every iteration, **deduplicated and ordered by consequence**,
   appended to rather than replaced. It costs nothing new — the findings already exist. This is
   the artifact a remake reads.
2. **R7 — remake is a recorded decision, informed by the digest** (`reviser.py` +
   `personas/code_author.md`). The remake trigger is a **judgement the reviser makes from
   evidence it already has** (failure counts, quality trend, share of cells implicated) — *not* a
   magic number. What must be deterministic is that the decision is **recorded** (a remake never
   happens silently). When a remake fires, the author receives the **accumulated digest**, not
   just the last brief.

## Files you own (collision map)
- `forged/pipeline/reviser.py` (digest build + remake decision), `personas/code_author.md`
  (remake/digest instructions), `forged/pipeline/state.py` (if the digest needs a `with_*` field),
  and this lane's tests under `tests/pipeline/`.
- **This is the hot-file lane.** While it is in flight, **no other lane may touch** `reviser.py`,
  `classify()`, `router.py`, `failure.py`, `personas/`, `graph.py`, `mode.py`. Lane 7 (UI backend
  seam) is additive and parallel-safe with this; the **author-split implementation (doc 23)
  serializes AFTER this lane** and must rebase onto post-R7 `master`.

## Constraints (beyond the shared ones in CLAUDE.md)
- **Immutability:** never mutate `PipelineState`; add a `with_*` builder if the digest lives on state.
- **Determinism where it counts:** the remake *decision* is recorded deterministically even though
  the *threshold* is a judgement — mirror how routing records its reasons.

## Verification (by deliverable — this changes LLM-judgement behaviour)
- **R6 offline check (doc 22 Part VI):** rebuild the digest from the four existing
  `revision_brief_v*.md` in `tests/corpus/doc22-regression-run/` (the in-repo fixture) and confirm
  the `PASSWORD` self-referential-validator finding **survives to the top** rather than being lost
  with its iteration. **Confirm this check can actually fail before trusting it** (R1's criterion
  mistake — a check that can't fail proves nothing).
- **R7:** its remake *behaviour* is the one thing needing a live rung — run the **Lane 1
  live-replay harness** (`.venv/bin/python -m pytest -m live tests/pipeline/test_live_corpus_replay.py`,
  needs `OPENAI_API_KEY`) before merge; the full paid artifact-lesson run is the final gate but
  belongs to the roadmap, not this PR.
- All three CI gates green (ruff / mypy / pytest ≥80%).

## Done means
Digest accumulates across iterations (offline-proven on the corpus, with a check that can fail);
remake is a recorded, digest-informed decision; live-replay run before merge; PR opened.
