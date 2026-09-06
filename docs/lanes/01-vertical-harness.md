# Lane 1 — Vertical-confirmation harness

**Branch:** `feat/vertical-confirmation-harness` · **Type:** code · **Depends on:** none
**Status:** in progress — corpus fixture placed; harness not yet written.
**Process:** see "Lane workflow" in root `CLAUDE.md`.

## Why this lane exists
Today every check on the pipeline is **horizontal**: unit tests and a mocked-LLM graph-integration
test (`tests/pipeline/test_graph_integration.py` — "All LLM interactions remain mocked"). They prove
the *plumbing* carries a value; they can never prove an **LLM critic produces a good judgement**. The
only **vertical** check (real input → real LLM → real routing → real output) is a full **paid run**,
which is manual, rare, and gated. So R2/R5 shipped "plumbing-validated only," and R6 will too.

This lane builds the missing middle rung: a **live, single-slice replay** that feeds real captured
notebooks through the *real* critics with a cheap model, for cents — not dollars.

## Scope
1. **Corpus fixture** — already placed at `tests/corpus/doc22-regression-run/` (the four real
   iterations from the 2026-08-13 run: `lesson_notebook_v*.ipynb`, `execution_report_v*_executed.ipynb`,
   `student_grade_report_v*.json`, `revision_brief_v*.md`). Being committed to git *is* its durable
   home now — it no longer depends on a gitignored `runs/` dir surviving.
2. **A `@pytest.mark.live` replay harness** (new file under `tests/pipeline/`, e.g.
   `test_live_corpus_replay.py`). It must:
   - load a corpus notebook + its execution report,
   - run the **real** Student and Reviewer agents against it with **gpt-5-mini** (cheap),
   - assert something weak-but-real per change:
     - **R2** — the critic no longer restates the execution failure verbatim,
     - **R5** — a `goal_fit` verdict is emitted and parses,
     - (later) **R6** — the digest surfaces the `PASSWORD` self-validator finding to the top.
   - The marker keeps it out of CI (see `tests/test_live_call_guard.py` — unmarked live calls are
     forbidden by design). It is a **manual pre-merge ritual** for LLM-judgement changes, run once.
3. **Document the ritual** in `TODO.md`'s R6 entry: run this harness before merging R6/R7.

## Files you own (collision map)
- `tests/corpus/**` (fixture, already added), `tests/pipeline/test_live_corpus_replay.py` (new)
- Possibly a small helper in `tests/` to load a corpus iteration.
- **Do NOT** modify pipeline logic here — this lane only *observes* it. If the harness reveals a bug,
  file it in `TODO.md`; the fix belongs to R6/R7 or a bugfix lane.

## Done means
`.venv/bin/python -m pytest -m live tests/pipeline/test_live_corpus_replay.py` runs a real gpt-5-mini
critic over the corpus and makes a real assertion about R2/R5 for cents (needs `OPENAI_API_KEY` +
`-m live`); the default suite still excludes it and stays green on all three gates. Open a PR.
