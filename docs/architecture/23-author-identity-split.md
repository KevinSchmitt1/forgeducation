# 23 — Author-identity split (code author vs artifact author)

**Status:** designed 2026-09-24 · ready to implement — but **implementation serializes after the
R6/R7 lane** (doc 22); see Part VI. This doc is design-only; its deliverable is validated by review,
not by a run.
**Follows:** doc 17 (lesson modes) established that a lesson is `executable` / `artifact` /
`conceptual`, purely planner-inferred. Doc 22 R5 established the goal-fit verdict. This doc addresses
one thing 17 left half-done: the *authoring identity* is still singular.

---

## The complaint (Kevin's framing)

> There is **one `code_author`** agent/node that runs regardless of lesson mode. For an `artifact`
> lesson (cells build+validate a file/config/scaffold) or a `conceptual` lesson (prose, nothing
> runs), "author some code" is the **wrong job description**. Split the `code_author` identity from
> the artifact/conceptual author.

The complaint is about **identity**, not plumbing. Doc 17 already made the *behaviour* mode-aware:
`personas/code_author.md` carries three inline branches, the executor runs whatever cells exist, and
the reviser threads mode into `classify()` and `assess_structure()`. What it did **not** do is split
the author's *self-description*. The file still opens:

> *"You are the **Code Author**… You produce notebook cells that implement the plan's **code demo**…"*

For an artifact or conceptual lesson that framing is wrong at the first sentence, and the mode
branches are patches bolted onto an identity that assumes compute-and-show. A learner-facing agent
authored by "you build and validate a deliverable" writes a different notebook than one authored by
"you implement a code demo, and by the way sometimes it's a file instead." The split makes the
identity match the job.

## Part I — The design decision, and the two axes it hides

The brief asks: *two personas or one mode-parameterized persona?* That question actually has two
independent axes, and conflating them is what makes this look like it touches every hot file:

1. **Persona axis** — one persona file with mode branches (today), or two files each with a clean
   identity.
2. **Topology axis** — one author *node* in the graph (today), or two nodes (`code_author` +
   `artifact_author`) each a distinct `PipelineStage`.

They are separable. You can split the persona identity **without** splitting the graph node. The
recommendation below does exactly that, and it is the whole reason the change is small.

### Recommendation: two personas, one node (internal mode dispatch)

| | Personas | Graph nodes | `PipelineStage` | Router / `failure.py` | Blast radius |
|---|---|---|---|---|---|
| **A — two nodes** | 2 | 2 (`code_author`, `artifact_author`) | +1 (`ARTIFACT_AUTHOR`) | **must become mode-aware** | graph + router + failure + state + config + personas |
| **B — one node ✅** | 2 | 1 (unchanged) | unchanged | **unchanged** | author agent + personas only |

**Recommend B.** Split the *persona* (`code_author.md` for `executable`; a new `artifact_author.md`
for `artifact` + `conceptual`), and let the **single author agent choose the persona from the
lesson mode it reads off the plan** — exactly the pattern the reviser already uses
(`RevisorAgent._extract_lesson_mode`). The graph node, the `PipelineStage`, the router, and
`failure.py` do not change.

**Why B over A:**

- **The identity that is wrong lives in the persona, not the topology.** Kevin's complaint is a
  first-sentence problem. Two persona files fix it completely. A second graph node fixes nothing the
  persona split doesn't already fix.
- **Mode is already a derived value, never a routed one.** Doc 17's deliberate choice: mode is *not*
  in `PipelineState`; every stage that needs it re-derives it from the latest `lesson_plan_v{N}`
  artifact via `extract_lesson_mode`. The author should follow the same rule — read the mode, pick
  the persona — rather than promoting mode into graph topology and the routing enum, which is the one
  thing doc 17 spent effort *avoiding*.
- **B sidesteps the router collision entirely** (Part III). A single node means the code-scope repair
  edge already lands on the one author, which re-derives mode on the repair pass. The requirement the
  brief flagged — *"route back to whichever author produced the notebook"* — is satisfied by
  construction, not by new routing code.
- **Least collision with R6/R7** (Part VI). Two nodes touch `graph.py`, `router.py`, `failure.py`,
  `state.py` — every hot file R6/R7 also edits. B touches `personas/` and one agent file.

The rest of the doc traces B concretely and states, for each touch-point the brief named, whether it
moves.

## Part II — What the split looks like

### The two personas

| Persona | Serves modes | Identity (opening) | "Seeing it work" |
|---|---|---|---|
| `personas/code_author.md` (**keep**) | `executable` | "You are the **Code Author**… you implement the plan's compute demo" | a cell produces real computed output |
| `personas/artifact_author.md` (**new**) | `artifact`, `conceptual` | "You are the **Artifact Author**… you **build and validate** the deliverables the plan names — files, configs, scaffolds, persona `.md`s, a loop harness — and in a conceptual lesson you **explain**, and say plainly nothing runs" | a cell **writes** an artifact and a cell **validates** it; conceptual: n/a, stated honestly |

Both are gpt-5-tier authors (real prose + real validated artifacts is not a cheap-model job). The new
file is not written from scratch — it is `code_author.md`'s artifact/conceptual branches promoted to
be the *whole* identity, with the executable-only material (the compute-demo framing, the
worked-example-with-numeric-output rule) removed rather than conditionalised. The shared machinery —
learner orientation, pipeline map, cell briefs, explanation-cell discipline, the patch-don't-rewrite
revision protocol (doc 21), the `%%writefile` trap, "stand-ins must announce themselves" — is common
to both and must stay identical between the files (see Part V on the DRY risk).

### The author agent picks the persona

`CodeAuthorAgent` (in `forged/pipeline/agents/code_author.py`) gains one responsibility: read the
plan's mode and select the persona. Concretely:

- Add a mode read mirroring the reviser's `_extract_lesson_mode` (read latest `lesson_plan_v{N}`,
  call `extract_lesson_mode`, default `executable` when absent).
- `_load_persona()` becomes mode-aware: `executable` → `code_author.md`; `artifact` / `conceptual`
  → `artifact_author.md`; anything else → `code_author.md` (the conservative default, matching
  `extract_lesson_mode`'s own fallback so a garbled mode never drops artifact rigor *or* mis-frames
  an executable lesson).

Everything else in the agent — the plan/brief user message, the patch-vs-full-notebook assembly, the
fallback cells, `next_stage() → EXECUTOR` — is unchanged. The persona selection is the entire code
delta.

> **Optional, not recommended for this change:** renaming the class to `AuthorAgent` and the node key
> to `"author"` reads better but ripples into `PipelineStage`, the router budget field, `graph.py`,
> and every test that names `code_author`. That is a cosmetic rename with real blast radius and no
> behavioural gain — defer it, or never do it. Keeping the `code_author` stage name is the KISS call.

## Part III — Every downstream part, traced (does it move?)

The brief named six touch-points. Under recommendation B, three do not move — and *that* is the
result, stated with the reasoning the brief asked for.

### 1. `forged/pipeline/graph.py` — **no change**

The brief anticipated "single author node becomes mode-dispatched." Under B the *agent* dispatches,
not the *graph*: `code_author_node` still calls `code_author.run(state, store)`, and the agent picks
the persona inside `run`. The node, the forward edges (`planner/gate → code_author → executor`), and
the revisor conditional edge (`code_author`, `content_reviser`, `planner`, `END`) are untouched. This
is the payoff of keeping one node.

### 2. `personas/` — **new file + one edit**

- **New:** `personas/artifact_author.md` (Part II).
- **Edit:** `personas/code_author.md` loses its artifact/conceptual branches and becomes the clean
  executable identity. Its shared sections are unchanged.

### 3. `config/pipeline.*.yaml` — **no new stage entry**

The brief anticipated a new stage → model entry. Under B there is no new stage: the single
`code_author` stage keeps its `gpt-5` / `max_tokens: 16384` entry and serves both personas. Adding a
per-mode model tier is YAGNI — both authoring jobs want gpt-5. The `stages:` list and `stage_models:`
map are unchanged.

### 4. `forged/pipeline/router.py` + `failure.py` — **no change** (the collision does not arise)

This is the touch-point the brief was most concerned about:

> *the `code`-scope / `content_reviser` return edges must route back to whichever author produced the
> notebook, not always `code_author`.*

Under a **two-node** design this is a real problem: `_CATEGORY_TO_STAGE` maps `CODE_QUALITY` and
`TEST_FAILURE` to a single `PipelineStage.CODE_AUTHOR`, so a code-scope repair on an artifact lesson
would route to the wrong author, and the map would have to become mode-aware — a change to
deterministic routing, the most safety-critical code in the pipeline.

Under **B there is one author node**, so the code-scope repair edge (`CODE_QUALITY` / `TEST_FAILURE`
→ `CODE_AUTHOR`) already lands on the only author, and that author **re-derives the mode from the
plan on the repair pass** and re-selects the correct persona. "Route back to whichever author
produced the notebook" is automatic: there is one author, and it is always mode-correct because it
reads the mode every time it runs. `router.py`, `failure.py`, the budget, and `_CATEGORY_TO_STAGE`
are all unchanged.

`CONTENT_QUALITY → content_reviser` is likewise unaffected: the content reviser is a mode-agnostic
prose rewriter (it improves explanations, it does not author artifacts), and its
`content_reviser → executor` re-entry is unchanged. It is correctly *not* split.

### 5. `forged/executor.py` — **no change; already aligned**

The executor is fully mode-agnostic and needs no author-split awareness. It runs every code cell in
whatever notebook it is handed (`allow_errors=True`) and reports per-cell results. Mode-appropriate
notebooks produce mode-appropriate execution *for free*: a `conceptual` notebook has zero code cells
→ `code_cell_count: 0`, `ok: True` (nothing to run, nothing fails); an `artifact` notebook's
write+validate cells run like any others. Doc 17's "no-ops conceptual / validates artifact" is an
emergent property of the executor operating on the author's output, not a branch in the executor. The
split changes *which persona* wrote those cells, not *what the executor does with them*. Confirmed
aligned.

### 6. Reviser + `classify()` — **no change; mode threading preserved**

`RevisorAgent.run` already derives mode once (`_extract_lesson_mode`) and threads it into both
`assess_structure(..., lesson_mode)` and `classify(..., lesson_mode)`. That path is entirely
independent of *who authored* the notebook — it reads the plan and the executed notebook, never the
author identity. Splitting the author does not touch any input the reviser reads, so mode threading
is preserved unchanged. The author now derives the same mode from the same artifact for its own
persona choice; the two derivations are independent reads of one source of truth (the plan), which is
exactly doc 17's model.

### Summary of movement

| Touch-point | Moves under B? | Why |
|---|---|---|
| `graph.py` | **No** | agent dispatches, not graph |
| `personas/` | **Yes** | new `artifact_author.md` + trim `code_author.md` |
| `config/pipeline.*.yaml` | **No** | one stage, both personas, same gpt-5 tier |
| `router.py` / `failure.py` | **No** | one node ⇒ code-scope edge already lands on the mode-correct author |
| `executor.py` | **No** | already mode-agnostic; alignment confirmed |
| reviser / `classify()` | **No** | reads the plan, not the author; mode threading intact |
| `forged/pipeline/agents/code_author.py` | **Yes** | reads mode, selects persona (the entire code delta) |

## Part IV — Test plan

New behaviour is small and almost entirely testable offline (persona selection is deterministic).

- **Persona selection (unit).** `AuthorAgent`/`CodeAuthorAgent` given a plan declaring each mode
  loads the right persona file: `executable → code_author.md`; `artifact → artifact_author.md`;
  `conceptual → artifact_author.md`; unknown/absent mode → `code_author.md` (default). Assert on the
  selected path, not file contents.
- **Persona-input assertion (unit).** On an artifact-mode plan, the system prompt handed to the LLM
  client is the artifact persona's text; on an executable/absent plan, it is the code-author text.
  This is the guard that the split actually reaches the model.
- **Routing per mode (unit / integration).** On an artifact lesson, a `TEST_FAILURE`/`CODE_QUALITY`
  classification routes to `CODE_AUTHOR` (the one node) exactly as today, and the author re-derives
  `artifact` mode on that repair pass and re-selects `artifact_author.md`. Proves the code-scope
  return edge lands on the mode-correct author without any router change.
- **No-regression on executable (the safety property).** Every existing `code_author` test stays
  green unchanged: an executable/unspecified lesson loads `code_author.md` and behaves byte-for-byte
  as before. The default path is untouched — this is the property that makes the change low-risk.
- **Both persona files parse / carry the shared contract.** A lightweight test that both files exist,
  are non-empty, and both still contain the invariants that must not diverge (e.g. the JSON-array
  output contract, the patch-revision protocol, the `%%writefile` guidance) — a cheap guard against
  the DRY drift in Part V.
- **LLM-judgement rung (deferred to implementation).** Per the lane-verify rules, a persona change is
  validated by the **Lane 1 live-replay harness** plus one paid run, confirming that
  `artifact_author.md` actually authors a better artifact lesson than the bolted-on branches did. This
  is *not* part of the design deliverable; it is the implementation's exit criterion.

## Part V — Risks

- **DRY drift between two persona files (the main risk).** The shared machinery (orientation, pipeline
  map, cell briefs, explanation discipline, patch protocol, `%%writefile`, stand-in naming) currently
  lives once, in `code_author.md`. Two files means two copies that can drift. Mitigations, in order of
  preference: (a) keep the shared sections verbatim-identical and add the Part IV test that both files
  carry the load-bearing invariants; (b) if drift becomes real, extract the shared sections into a
  common include the agent concatenates ahead of the mode-specific identity — but that is a
  YAGNI-until-proven refactor, not part of this change. Do **not** pre-build the include; the personas
  are prose, and premature templating of prose is its own maintenance cost.
- **Two independent mode reads (author + reviser).** Both derive mode from the plan artifact. They can
  only disagree if the plan changes between the author pass and the reviser pass — which it cannot
  within one iteration — so this is safe. Documented so a future reader does not "fix" it by threading
  mode through state (which doc 17 deliberately declined to do).
- **Conceptual authored by an "artifact" author.** Pairing `conceptual` with `artifact_author.md`
  (per the brief) is right — both are "build/explain, not compute-and-show" — but the persona must
  make the conceptual branch first-class and honest ("nothing runs; say so"), not a footnote to
  artifact authoring. This is a persona-quality requirement for the implementation, flagged here.

## Part VI — CRITICAL sequencing: serialize implementation after R6/R7

**Design completes now. Implementation must serialize after the R6/R7 lane (doc 22).**

R6 (`critique_digest` accumulates findings) and R7 (remake is a recorded decision, informed by the
digest) both edit `personas/code_author.md` and touch the author agent — the exact surface this split
edits. Doc 22 Part V sequences R6→R7 before this. Two consequences:

1. **File collision.** R6/R7 and this split both modify `personas/code_author.md` and
   `forged/pipeline/agents/code_author.py`. They cannot both be in flight; per `TODO.md` they
   serialize, R6/R7 first.
2. **The split must inherit R7's persona language.** R7 adds remake/digest instructions to the author
   persona. If the split lands *after* R7 (recommended), `artifact_author.md` is forked from a
   `code_author.md` that *already* carries the R7 remake/digest sections, so the new file inherits them
   in one copy. If the split were to land first, R7 would have to apply its persona changes to **both**
   author files — more work and a fresh drift risk. Landing the split after R7 is therefore both the
   collision-safe order and the DRY-cheaper one.

**Order of record:** R6 → R7 → author-identity split, all on the shared-hot-file serialization queue
tracked in `TODO.md`. When implementing, rebase onto the post-R7 `master`, fork
`artifact_author.md` from the then-current `code_author.md`, then trim each file to its identity.

## Part VII — Confidence

**Designed, reviewed against the live code, not implemented.** Every "no change" claim in Part III
was checked against the current `graph.py`, `router.py`, `failure.py`, `executor.py`, and
`reviser.py` on `docs/author-split-design`. The design's correctness rests on one structural fact —
the pipeline routes to a single author *node* and derives mode from the plan artifact, not from state
— which is verified in the code, not assumed. No runtime behaviour has been exercised, because the
deliverable is this document; the implementation's own rungs (exercised on all three modes, then the
Lane 1 replay + one paid run) are in Part IV.
