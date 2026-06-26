# 14 — Code explanation & learner readiness

**Status:** IMPLEMENTED (persona quick-wins). The escalation workflow in Part III is **designed,
not built** — it is the next feature.

## Why

A real run on *"How to setup and train local LLMs on Apple Silicon M1"* for a learner with no
PyTorch/tensor/LoRA background exposed two failures the existing honesty machinery did not catch:

1. **Concept→code cliff.** The notebook explained LoRA conceptually, then dropped the learner into
   `LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, …)` with no key to decode the parameters.
   The `code_author` persona mandated *concept* explanation but never *parameter/construct-level*
   explanation, so dense calls landed unexplained.
2. **Silent artifacts.** The notebook trained and saved a real PEFT adapter
   (`adapter_config.json` + `adapter_model.safetensors`) and never told the learner the files
   existed or why.

Underneath both sat a deeper flaw: the planner, when prerequisite gaps were *too many or too
deep*, was instructed to **"reduce the depth of background"** — i.e. cram foundational concepts
(tensors, neural-net training, LoRA) shallowly into one lesson. That instruction *manufactured*
the unfollowable density. You cannot honestly teach LoRA fine-tuning in one lesson to someone who
doesn't know what a tensor is.

This is the **fourth honesty rule**, alongside the existing three (R1: don't silently drop a
capability; orientation: don't silently assume a prereq; curriculum: don't drop/re-teach across a
course): **don't silently cram a topic past the learner's foundation.**

## Part I — Code maps & cell briefs (`code_author`, enforced by `student`/`reviewer`)

Make dense code followable *without* bloat, via three devices in `personas/code_author.md`:

1. **One ASCII pipeline map** (when the lesson is a multi-step process), right after the
   orientation: each step a labelled box, arrows for what flows between them, plain words, new
   primitives named on first appearance, and **the files the pipeline writes shown as their own
   box**. ASCII because it renders identically in every notebook surface (no extension, no
   execution) — chosen over Mermaid (breaks in classic Jupyter/nbconvert) and generated images
   (another dense, failure-prone code cell). The map is the shared reference, so later cells need
   only a thin pointer.
2. **A short per-cell brief** before any dense/new-construct cell — kept short *because the map
   framed it*: *where we are* (map step) → *decode the call* (name each meaningful parameter, what
   it controls, why this value) → *new construct* (one plain line).
3. **Surface what the code writes** — the markdown after any file-writing cell must say what was
   created, where, what's inside, and why.

**Enforcement** (so the revision loop fixes regressions): `personas/student.md` flags a dense cell
with no brief and any "silent artifact" — both scoped `content` (the step works, it just isn't
explained, so the loop *adds the explanation and keeps the step*, never `plan`/`structure` which
would amputate). `personas/reviewer.md` checks the *decoded* parameter explanations are
*correct*, not merely present.

## Part II — Readiness verdict (`planner`)

`personas/planner.md` now makes a **readiness verdict** in the gap-analysis step. When the GAPs are
**foundational** (the topic is unintelligible without them) AND too deep for one honest lesson, the
planner must NOT cram. Instead:

1. **Scope to a teachable beachhead** — the furthest point this learner can honestly reach on what
   they already know.
2. **Declare the un-reachable capability as a topic-fidelity gap**, reason *"requires prerequisites
   the learner lacks: …"* — surfaced via the existing `TopicFidelitySignal`, never silently
   dropped (this *satisfies* R1: be honest, don't pretend).
3. **Name the missing foundations + the path** in the orientation (a course-shaped sequence).

It reuses everything already built: the KNOWN/GAP map (orientation, doc 12), the fidelity signal
(R1, doc 11), and — for the real sequencing — the curriculum decomposition (doc 13).

## Part III — Escalation workflow (DESIGNED, next feature)

The readiness verdict is the *detection*. The agreed *response*, to be built next as its own
plan + doc:

`forged agentic` runs the planner → if the readiness verdict is "gap too deep," it does **not**
build a single lesson. It calls the **curriculum planner** to produce a course *plan* (N modules,
topics, order), shows the learner the preview (`COURSE.md` + rough cost/time), and **stops** —
asking for explicit confirmation before any paid build.

Agreed design decisions (record so they aren't relitigated):
- **Single smart front door:** the learner always inputs just a topic; the system decides
  single-lesson vs course.
- **Confirmation UX:** interactive, **plan-only by default** — nothing paid runs without an
  explicit go (a `--yes` flag skips the prompt for automation). Chosen over auto-proceed because
  it doubles as a spend gate (a course is N paid notebook builds).
- **Reuse, don't rebuild:** `forged course --plan-only` already produces the preview
  (`course_plan.json` + `COURSE.md`); curriculum decomposition (doc 13) already exists. The new
  pieces are only: the auto-route on the verdict, and the confirmation gate.

This is also the natural home for the curriculum planner's Phase 4 (reactive re-decomposition):
readiness-triggered decomposition and capability-overflow re-decomposition share machinery.

## Validation

- `tests/pipeline/test_pedagogy_persona.py` — persona-contract tests pin every mandate above so it
  cannot be silently deleted (same pattern as `test_orientation_persona.py`, doc 12).
- A clean live validation needs a **provisioned** agentic run (so the `transformers` version is
  pinned and cells execute) on the same M1/LoRA topic, then a read of the notebook to confirm the
  map, the per-cell briefs, the surfaced adapter files, and an honest readiness scope-down/​verdict.
