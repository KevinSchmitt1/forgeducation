# 20 — Artifact lessons that author documents: the delimiter collision

**Status:** diagnosed from a real run, changes scoped, not implemented (2026-08-13)
**Run:** `runs/20260813-201647_create_and_validate__github_co/` — 1016.7s, 172,247 tokens,
12 calls, **no acceptable notebook**. Terminal reason: *"Code needs fixing, but code author
budget exhausted."*

This is the first `artifact` lesson ever built end-to-end (doc 17 shipped the modes; doc 18
made the planner actually pick them). It failed, and the failure is specific to what
artifact lessons do.

---

## What happened

Topic: write `.github/copilot-instructions.md` + `AGENTS.md` for a Python repo and validate
them. The planner correctly produced **1 module, `mode: artifact`** — the machinery from
docs 17/18 worked. Then four `code_author` iterations each produced a notebook that would
not run.

| Iteration | Failed cells | Error | Student quality |
|---|---|---|---|
| v0 | 4, 7, 9, 12, 14, 17, 19, 21 | `IndentationError: unexpected indent` (line 5) | 74 |
| v1 | 16 | `SystemExit: Validator did not emit JSON_REPORT=…` | 82 |
| v2 | 12, 17, 20 | `SyntaxError: invalid syntax. Perhaps you forgot a comma?` (line 3) | 74 |
| v3 | 7, 9, 12, 14, 17, 19, 22 | `SyntaxError: invalid syntax` (line 44) | 71 |

Every route was `code_quality`. Failing cells differ each iteration and quality drifts
*down*: this is not convergence, it is re-rolling.

## Root cause: the content and its container use the same delimiter

An instruction file for a coding agent **is mostly code examples**. The notebook writes that
file by embedding its content in a Python string literal. The examples contain docstrings.
The docstring closes the literal.

`execution_report_v3_executed.ipynb`, cell 7 — the error is at line 44, exactly here:

```python
instructions_md = r"""              # line 7  — opens the literal
# Copilot repository instructions
...
```python
def load_config(path: Path) -> Dict[str, Any]:
    """Load configuration from a path using project utilities."""   # line 44 — CLOSES it
```

Same family in v2 cell 12 (`agents_md = dedent("""` → `SyntaxError` at line 3).

**The better the file content, the more certain the cell is to be unparseable.** A
`copilot-instructions.md` worth writing contains before/after code snippets with docstrings;
a `AGENTS.md` worth writing contains task templates in fenced blocks. The lesson's quality
and the cell's parseability are in direct opposition. This is not a code_author slip — it is
a structural trap in authoring-a-document lessons, and it will recur on every such topic.

## Why four iterations could not escape it

`revision_brief_v2.md` told the author:

> **Reason**: Code failed to run. Cells [12, 17, 20] raised errors.
> **Error**: `SyntaxError: invalid syntax. Perhaps you forgot a comma? (line 3)`

That is the symptom. The mechanism — *the text you are embedding contains the delimiter you
are embedding it with* — is never stated. The Student got closest ("inspect the cell content
for an unclosed string") but framed it as a slip to re-check, not a structural conflict. So
the author rewrote the notebook the same way and re-collided.

Compounding it: a `code_quality` route re-invokes `code_author` for a **whole new notebook**,
not a patch. `code_author` spent 4 calls / 49,950 output tokens / 16,512 reasoning — 74K of
the run's 172K — regenerating around a bug nobody had named.

## Secondary findings

**1. The Reviewer's response was truncated and then discarded.**
`config/pipeline.review-loop.yaml` sets `reviewer: max_tokens: 4096`. For OpenAI reasoning
models this is sent as `max_completion_tokens` (`forged/llm.py:285`), which **includes
reasoning tokens**. `USAGE.md` shows the reviewer averaging ~2,325 reasoning + ~3,267 output
per call ≈ 5,600 against a 4,096 ceiling. Iteration 2 therefore had **no expert critic at
all** (`reviewer_report_v2.json` is 150 bytes; SUMMARY records the `review_failed`
degradation honestly).

The defect is not the number. It is that a truncated response costs a full paid call and
returns **nothing**. `finish_reason='length'` is a recoverable condition being treated as a
fatal one.

**2. The plan asked for work a notebook cannot honestly do.**
`lesson_plan_v0.md` objectives included *"commit the files to the repository"* and
*"recommending CI integration"*. The notebook duly ran `git add` — against the **user's real
repository**, producing `fatal: pathspec '.github/copilot-instructions.md' did not match any
files` in the run log.

Then the topic-fidelity detector reported *"…iterate on the files until validation passes,
and commit the files to the repository"* as a **DROPPED capability** (SUMMARY.md → Topic
Fidelity). So the honesty machinery was actively pressuring the pipeline to keep attempting
an operation that cannot succeed or be verified in a notebook. Two safeguards pushing in
opposite directions.

**3. The cost estimate models one pass, not a revision loop.**
`gate.py` assumes `EST_TOKENS_PER_LESSON = 100_000`. This run used **172,247** because it
iterated four times. The gate quoted ~$0.20–$0.50; the real spend was materially higher. The
estimate is not wrong about a *clean* lesson — it is silent about the loop, which is exactly
where cost runs away.

## What we are deliberately NOT doing

**Not a syntax gate.** The obvious fix — `ast.parse` every cell after `code_author` and route
back without executing — was rejected. Execution already collects **all** failing cells
(`execution_report_v0` lists eight), so the gate adds no breadth; and it would hide **runtime**
failures that the same execution finds (v1's `SystemExit` in the validator is invisible to
`ast.parse`). Kernel time costs **no tokens**, while an extra iteration costs a full gpt-5
notebook. Trading money to save wall-clock is the wrong direction.

**Not a blacklist of forbidden operations.** Enumerating banned verbs (`git commit`, `pip
install`, network calls) fails the way the package allow-list failed: it was questioned twice,
defended twice, and cost two paid module builds before being removed (`TODO.md`; PR #31). Any
list is simultaneously too narrow (the next un-runnable objective is not on it) and too broad
(a lesson *about* git legitimately runs git in a scratch repo). The rule must be a criterion
the model applies, not a set the model is checked against.

## The changes

Three of the four are persona/prompt text. That is the right shape for this repo — behavior
lives in `personas/`, and a principle generalizes where a rule does not.

### C1 — Name the collision in the revision brief (deterministic, free)

When execution reports a `SyntaxError`/`IndentationError` **and** the offending cell contains
a triple-quoted string whose body contains `"""`, `'''` or a ```` ``` ```` fence, the brief
must say so in one sentence: *the content being embedded contains the delimiter used to embed
it; use a mechanism that does not re-parse the content.*

This is a diagnosis added to information we already have — it skips nothing and hides nothing.
Detection is a string check on the failing cell's source; no LLM involved.

### C2 — Teach `code_author` how to write a file whose content is code

`personas/code_author.md` currently says artifact cells "write and validate" but says nothing
about *how* to write content that is itself code. Add the idiom, with `%%writefile` named as
the primary tool: Jupyter's cell magic writes the remainder of the cell to a path **verbatim**,
with no Python string literal involved and therefore no delimiter to collide with. Where the
content must be computed rather than literal, the persona should prefer building from a list
of lines over one large literal.

Framed as craft guidance ("here is how this is done well"), not a prohibition.

### C3 — A verifiability principle at plan time, replacing any list

Add to `personas/planner.md` (and its curriculum sibling) a criterion the planner applies to
every objective it is about to write:

> **Can a cell in this notebook carry this out and show the learner it worked, using only
> what the notebook itself creates?** If it cannot, it is context for the prose — not an
> objective, and not a cell.

Consequences follow from the principle without being enumerated: committing to *the learner's*
repository fails it (the notebook cannot create or verify that repo state); building a demo
repository in the run directory and committing *there* passes it (self-contained and
observable). The lesson may still *discuss* CI integration in markdown — it just stops being
a thing the notebook claims to have done.

This also resolves finding 2's contradiction at the source: an objective that never gets
written is never reported as a dropped capability, so no filter is needed downstream.

### C4 — Treat `finish_reason='length'` as recoverable

A truncated grader response must not cost a full call and yield nothing. Options, cheapest
first: retry once with a raised ceiling; or persist the partial content and parse what is
there; or shrink the grader schema. The per-stage `max_tokens` values in
`config/pipeline.*.yaml` should also account for reasoning tokens counting against
`max_completion_tokens` — but the config value is a setting, not the fix.

## Validating this without spending

The run left **four failing notebooks** in place. That is a regression corpus, and C1 and C2
are checkable against it offline, for $0:

- C1: the collision detector must fire on v2 cell 12 and v3 cell 7, and must **not** fire on
  v0 cell 4 (a genuine stray-indent slip) or v1 cell 16 (a runtime `SystemExit`). Precision
  matters more than recall — a detector that cries collision on every SyntaxError teaches the
  author to ignore it.
- C2: a `%%writefile` cell carrying v3's exact `copilot-instructions.md` content must parse
  and execute where the triple-quoted version does not.

C3 is a planner-behavior change and can only be observed on a real plan — but `--plan-only`
prices that at one `gpt-5-mini` call, so it is checkable for cents before any build.

## Open questions

1. **Should a `code_quality` route patch instead of regenerate?** Asking for only the failed
   cells would cut the dominant cost (74K tokens on `code_author`). It is a real change to the
   revision contract and deserves its own doc — noted here because this run is the evidence
   for it.
2. **Should the loop stop when it is not converging?** Failing-cell counts of 8 → 1 → 3 → 7
   with quality 74 → 82 → 74 → 71 is a random walk that consumed the whole budget. A
   non-convergence exit would have saved roughly half this run.
3. **Should the gate's estimate model iterations?** The 100K/lesson constant describes a clean
   pass; every run that needs revision exceeds it silently.
