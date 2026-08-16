# 21 — Patch, don't regenerate (C5), and the non-convergence signal (C6)

**Status:** designed, not built (2026-08-16)
**Evidence:** `runs/20260813-201647_create_and_validate__github_co/` — the run analysed in
[doc 20](20-artifact-lessons-that-author-documents.md).
**Implements:** C5 and C6, promoted from doc 20's open questions after review.

---

## The finding that reframes this

`code_author` does not regenerate the notebook *by choice*. It regenerates because **it has
never seen the notebook it wrote.**

`CodeAuthorAgent._build_user_message` (`forged/pipeline/agents/code_author.py:120`) assembles
exactly three things:

```
context prefix  +  "Lesson Plan: …"  +  "Feedback from previous attempt: …"
```

The previous `lesson_notebook_v{N-1}` is not among them. So on a `code_quality` reroute the
author receives a plan, a complaint about cells it cannot see, and no artifact — and the only
thing it *can* do is write a fresh notebook from the plan. Every iteration re-derives 20+
cells to fix two.

This is not a prompt problem. Asking the persona to "only change what is broken" cannot work
while the thing to change is absent from the inputs.

## What it costs

From that run's `USAGE.md`:

| stage | model | calls | input | cached | output | reasoning | total |
|---|---|---:|---:|---:|---:|---:|---:|
| code_author | gpt-5 | 4 | 24,094 | 46.2% | 49,950 | 16,512 | **74,044** |

**43% of the whole run**, at ~12,488 output tokens per call — a complete notebook each time.
The four notebooks were **24, 21, 24 and 26 cells**; the failures were **8, 1, 3 and 7** cells,
most of them cascading from one root. Iteration v1 is the sharpest case: 21 cells rewritten to
repair **one**.

The trade this design makes is **input for output**. Handing the author its previous notebook
adds input tokens (large, but ~46% already cache-hits on this stage) and removes most output
tokens (the expensive, uncacheable half — see `TODO.md` → Cost findings). That is the right
direction on this bill, and it is the reason C5 outranks `reasoning_effort` as a lever.

## Why patching is safe here

Cell indices are stable between what the author wrote and what the executor reports. Verified
on the corpus:

```
v0: authored=24  executed=24  indices_aligned=True
v3: authored=26  executed=26  indices_aligned=True
```

The executed notebook is a 1:1 copy with outputs attached, so `execution_report.failed_cells`
indexes directly into `lesson_notebook_v{N-1}`. A patch keyed by cell index needs no
translation layer.

## The design

### 1. Give the author what it is being asked to fix

On a reroute where a previous notebook exists, `_build_user_message` gains it — **cell-indexed**,
matching the indices the brief already cites. The plan and brief stay exactly as they are.

Indexing matters: the brief says "cells 12, 17, 20 raised errors", and the author must be able
to find cell 12 without counting.

### 2. Allow a patch as the response, without requiring one

`forged/notebook.py` currently accepts a bare cell array or `{"cells": [...]}`. It gains a
third accepted shape:

```json
{"patch": [{"index": 7, "type": "code", "source": "…"}]}
```

and a deterministic `apply_patch(notebook_json, patch) -> notebook_json` that replaces those
cells and leaves every other byte alone.

**The full-notebook shape keeps working, and that is deliberate.** Some fixes cannot be a
patch — a bug whose real repair is splitting one cell into two, or moving an import earlier.
The author chooses; it is not forced into a mode it cannot satisfy. This is the same principle
as doc 20's no-blacklist decision: give the model the option and the information, not a rule
that is wrong a quarter of the time.

Replace-only to start. Insert/delete is deferred — the full rewrite already covers those
cases, and an index-shifting patch format is a much larger contract for a need we have not
observed. (YAGNI.)

### 3. Validate the merge like any other boundary

`apply_patch` refuses, with an actionable message, an index out of range, an unknown cell
type, a non-string source, or a patch that leaves the notebook unparseable as nbformat. A
malformed patch degrades to the existing "author returned something unusable" path — the same
`llm_empty_fallback` degradation, recorded honestly — never a silently half-applied notebook.

### 4. Cascades: patch the root, not the symptoms

v0 failed on eight cells; nearly all were consequences of one broken cell earlier. A patch
listing all eight would be as expensive as a rewrite and would "fix" cells that were never
wrong.

Nothing mechanical decides this — the brief already carries what is needed. C1 (PR #41) names
the *mechanism* and the specific cells showing it, which is precisely the signal that
distinguishes a root from a cascade. The persona should say so plainly: repair the earliest
cell that genuinely differs from what the plan asked for, then let re-execution reveal what
remains.

## C6 — the non-convergence signal

A hard exit at a threshold was rejected in review: a run one iteration from working would be
killed and the learner would get nothing. Instead the loop is made **aware**.

When repeated attempts have not reduced the failures, the brief adds:

> Two attempts have not reduced the failures. **Look for a systematic cause** — the same
> underlying mistake may be recurring in different cells. Re-examine the failing cells from a
> different angle before changing anything else.

**The wording is load-bearing and was narrowed deliberately.** "Change your approach" invites
a rewrite — exactly the expensive behaviour C5 exists to remove. "Look for a systematic cause"
asks for a shift in *perspective* while keeping the work targeted, which is what all four
iterations of that run failed to do: each treated a recurring structural collision as a fresh
local slip.

Trigger: the failed-cell count has not decreased across two consecutive iterations. The run
that motivates it went `8 → 1 → 3 → 7` failing cells with quality `74 → 82 → 74 → 71`; the
signal should fire at iteration 2, where the count rose again after the improvement at v1.

It never terminates, never routes anywhere new, and never suppresses the rest of the brief.

## Test plan

Offline, no spend:

- `apply_patch`: replaces the named cells and nothing else; preserves cell count and every
  untouched cell byte-for-byte; rejects out-of-range index, unknown type, non-string source;
  round-trips through `nbformat`.
- the parser accepts all three shapes, and a `{"cells": …}` response behaves exactly as today
  (a regression test written before the change).
- `code_author` includes the previous notebook in its inputs when a brief exists, and does
  **not** on the first pass (nothing to patch).
- C6 fires on the real trend `8 → 1 → 3 → 7` at iteration 2, and does not fire on a
  monotonically improving trend.
- the merged notebook after a patch still passes the anti-hollow structural gate.

The corpus in `runs/20260813-201647_…/` supports a stronger check than unit tests: apply a
hand-written patch for v3's two colliding cells to `lesson_notebook_v3.ipynb` and execute the
result. If it runs green, C5's premise — that these failures were repairable in place — is
demonstrated rather than assumed. That is worth doing before writing the persona half.

## Open questions

1. **Should the author be told how many tokens a rewrite costs?** It has no cost signal today.
   Probably unnecessary once the notebook is in the inputs — patching is the path of least
   effort when the artifact is right there — but worth watching in the first run.
2. **Does the student/reviewer need to know a patch happened?** Currently they judge the
   merged notebook, which is correct and mode-agnostic. No change proposed; noted because a
   future "what changed since last iteration" critic prompt would need it.
3. **Interaction with `content_reviser`.** It rewrites prose on the `CONTENT_QUALITY` route and
   has the same never-sees-its-own-output shape. Out of scope here; if C5 works, the same
   change is likely worth making there.
