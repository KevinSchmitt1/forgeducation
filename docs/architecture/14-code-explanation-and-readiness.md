# 14 — Code explanation & learner readiness

**Status:** ✅ IMPLEMENTED, all parts (2026-07-20). Parts I–II shipped as persona quick-wins.
**Part III (escalation workflow) implemented**: new `ReadinessVerdict` (frozen, in
`forged/curriculum/model.py`), `forged/curriculum/readiness.py::ReadinessAssessor` (mirrors
`CurriculumPlanner`/`PlanAdjuster`'s shape — persona file + `LLMClient.complete` with strict
`response_format`, fails open to `reachable=True` on any parse failure or LLM error),
`personas/readiness_assessor.md`, and a pre-flight wired into `forged/cli.py::_cmd_learn` via
`_apply_readiness_preflight`/`_readiness_escalation_guidance` — runs only when the
`CurriculumPlanner` sizes a topic to exactly 1 module; on an unreachable verdict, escalates via
a guided Tier-2 re-plan (the same guidance channel the front-door gate's `PlanAdjuster` uses)
into the existing, unchanged gate/build path. `forged agentic` is untouched. Validated by
`tests/test_curriculum_readiness.py` (20 tests: schema forwarding, reachable/unreachable
parsing, fail-open on parse failure/LLM exception/missing field, context guard, persona
contract) and `tests/test_cli_learn.py` extensions (assessor called exactly once on a 1-module
reachable plan, escalation with guidance + gate shown, assessor never called on an N-module
plan, `--yes` + not-reachable escalates and skips the gate, non-TTY-without-`--yes` on an
escalation still `EXIT_USAGE`, cancel-after-escalation still `EXIT_OK`/nothing run). All three
CI gates green (583 passed, 92.57% coverage; `readiness.py` itself at 90%).

**Caught during implementation, not a Part III design flaw:** the first wiring pass constructed
a real `ReadinessAssessor` (and thus a real `LLMClient`) whenever a test's 1-module course
wasn't mocked — this made 3 pre-existing `test_cli_learn.py` tests issue live, unconsented
OpenAI calls before the mock was added. Fixed by patching `cli.ReadinessAssessor` in every test
that reaches the pre-flight (mirrors how every test already patches `cli.CurriculumPlanner`).
Flagging here so a future persona/agent addition following this same "construct-a-real-client-
by-default" pattern remembers to mock it in every existing test path, not just new ones.

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

## Part III — Escalation workflow — ✅ IMPLEMENTED (2026-07-20)

The readiness verdict is the *detection*. The response, scoped via a dedicated research pass:

**Supersession note, recorded so it isn't silently missed:** doc 16 (`16-smart-front-door.md`
decision 2) *deliberately* rejected adding a readiness signal to sizing — *"Sizing = the
curriculum planner itself… No new 'readiness' signal, no second sizing heuristic."* It also
already built the two pieces this section originally called "the new pieces": the confirmation
gate (`forged/curriculum/gate.py::run_gate`) and the plan-first/confirm-before-spend UX
(`forged/cli.py::_cmd_learn`). What Part III still owes, after that supersession, is narrower
than the original sketch: **a pre-flight check that catches a topic `CurriculumPlanner` sized
down to 1 module, but that is too hard for *this learner's* profile** — before any gpt-5 spend on
a beachhead the learner didn't ask for. Phase 4's reactive safety net (doc 13) already catches the
same overflow *after* a wasted build; this is the proactive, cheaper-but-narrower sibling.
**Decision recorded 2026-07-20: build it** (see resolved design decisions below).

### Structured shape

New frozen dataclass — deliberately **not** an extension of `TopicFidelitySignal` (that signal is
post-execution, deterministic, and doc 11 pins it "stable and additive-only" as the R1↔curriculum
coupling contract; overloading it with a pre-execution LLM verdict would blur that seam):
```python
@dataclass(frozen=True)
class ReadinessVerdict:
    """Whether this topic is honestly reachable for THIS learner in one lesson.

    Produced BEFORE any build (pre-execution, LLM) — the input-side counterpart to
    TopicFidelitySignal's post-execution drop detection.
    """
    reachable: bool
    beachhead: str                            # furthest honest single-lesson scope, if we proceeded
    missing_foundations: tuple[str, ...]      # prereq concepts the learner lacks, in learn order
    unreachable_capabilities: tuple[str, ...] # requested capabilities out of reach this lesson
    reason: str
```
It stays outside `PipelineState` — a CLI/curriculum-layer value object, never entering the graph
(see routing decision below); adding a state field we don't route on would be speculative.

### New wrapper, not a reuse of the lesson planner's prose

New `forged/curriculum/readiness.py::ReadinessAssessor`, mirroring `CurriculumPlanner`
(`curriculum/planner.py`) and `PlanAdjuster` (`curriculum/adjuster.py`) exactly: persona file
(`personas/readiness_assessor.md`) + `LLMClient.complete(..., response_format=...)` per the doc-15
structured-output pattern, injectable `llm_client`, `DEFAULT_MODEL="gpt-5-mini"`, lenient
`_extract_json_object` fallback for non-OpenAI providers. The lesson `PlannerAgent` outputs
markdown (consumed by `code_author`), which is incompatible with a whole-response JSON schema —
doc 15 already ruled out "prose plus trailing fenced JSON" as unreliable, so a dedicated
structured call is the doc-15-consistent choice over parsing the markdown plan's prose.

### Where the check lives — CLI pre-flight in `forged learn`, not a graph node

Sits between the front door's existing up-front sizing and the gate, inside `_cmd_learn`: after
`CurriculumPlanner.plan` returns exactly 1 module, call `ReadinessAssessor`; if
`reachable is False`, re-plan via `CurriculumPlanner.plan(..., guidance=...)` (the same Tier-2
guidance channel the gate's `PlanAdjuster` already uses) synthesized from
`missing_foundations`, producing an escalated N-module course that flows into the **existing,
unchanged** `_run_plan_gate` → `_build_confirmed` path.

Rejected alternative: a graph-halt node (a conditional edge after `planner` that ENDs early,
mirroring `_continue_unless_terminal`). `router.py`/`failure.py` classify *post-execution*
signals (execution report, grade report, structural report); a pre-execution planning verdict
doesn't fit that model, and a graph node still has to pop back out to the CLI for the interactive
gate — more moving parts than the pre-flight, no cost advantage. `forged agentic` is **left
unchanged**: its non-interactive contract is load-bearing (doc 16 decision 1; `run_course`
composes it), and its existing honest behavior on a too-deep topic (persona-level beachhead
scoping + surfaced `TopicFidelitySignal` in SUMMARY.md) is appropriate for a power-user,
non-interactive command.

### Resolved design decisions (record so they aren't relitigated)

- **Build it** (over: fold into `CurriculumPlanner`'s profile-awareness + rely on Phase 4 alone).
  Decided 2026-07-20 — the narrow pre-build-vs-post-build-waste tradeoff is worth the scoped cost.
- **Single smart front door:** the learner always inputs just a topic; `forged learn` decides
  single-lesson vs. course, now including this pre-flight. `forged agentic` is untouched.
- **`--yes` threading:** no new flag. The escalation slots in before `_cmd_learn`'s existing
  `args.yes` branch — an escalated topic still respects `--yes` (skip gate, build the escalated
  course) and the existing non-TTY-without-`--yes` → `EXIT_USAGE` rule.
- **Fail-open on assessor parse failure:** degrade to the single-lesson build (conservative
  spend; R1 + Phase 4 remain the runtime backstop), not an escalation — mirrors `PlanAdjuster`'s
  "degrade to the non-destructive default."
- **Accept the double-planning cost:** the pre-flight assessor call plus the lesson planner's own
  re-plan inside `run_pipeline` (non-escalated case) is one extra gpt-5-mini call. Accepted for
  now (KISS); threading the pre-flight result into `run_pipeline` to skip the re-plan is a later
  optimization, not required for v1.

### Tests

`tests/test_curriculum_readiness.py` (mirrors `test_curriculum_adjuster.py`): forwards the
strict JSON schema via `response_format`; parses `reachable: True`/`False` verdicts; unparseable
response degrades to the fail-open default (pins the Q4 decision); context guard (only brief +
learner context + topic_spec reach the prompt, no plan/notebook leakage). Persona-contract test
extending `tests/pipeline/test_pedagogy_persona.py`'s pattern for `readiness_assessor.md`
(verdict vocabulary, the "requires prerequisites the learner lacks" reason mandate, JSON-only
output rule) — the existing planner-persona readiness tests are kept as-is, since the planner
persona still governs in-pipeline beachhead scoping for lessons that do proceed.
`tests/test_cli_learn.py` extension (mocked `ReadinessAssessor` + `CurriculumPlanner`): 1-module +
reachable → single-lesson path, assessor called once, no escalation; 1-module + not-reachable →
re-plan with guidance, gate shown, `run_course` invoked; N-module plan → assessor not called
(pre-flight is 1-module-only); `--yes` + not-reachable → escalates, skips gate; non-TTY without
`--yes` on an escalation → `EXIT_USAGE`; cancel at the gate after escalation → `EXIT_OK`, nothing
run.

**Files touched (as built):** new `forged/curriculum/readiness.py`,
`personas/readiness_assessor.md`, `tests/test_curriculum_readiness.py`; `ReadinessVerdict` landed
in `forged/curriculum/model.py` alongside `ModuleSpec`/`CourseSpec` (it never enters
`PipelineState`) — `state.py` untouched; edited `forged/cli.py` (`_apply_readiness_preflight`/
`_readiness_escalation_guidance` + `_cmd_learn` wiring) and `tests/test_cli_learn.py`
extensions. **Deviation from the original sketch:** persona-contract tests for
`readiness_assessor.md` live inside `test_curriculum_readiness.py` itself (mirroring
`test_curriculum_adjuster.py`'s own bottom section), not `tests/pipeline/test_pedagogy_persona.py`
— that file covers the lesson-loop personas (`code_author`/`student`/`reviewer`/`planner`);
`readiness_assessor.md` is a curriculum-layer persona like `plan_adjuster.md`/
`curriculum_planner.md`, which already keep their contract tests in their own module's test file.

## Validation

- `tests/pipeline/test_pedagogy_persona.py` — persona-contract tests pin every mandate above so it
  cannot be silently deleted (same pattern as `test_orientation_persona.py`, doc 12).
- A clean live validation needs a **provisioned** agentic run (so the `transformers` version is
  pinned and cells execute) on the same M1/LoRA topic, then a read of the notebook to confirm the
  map, the per-cell briefs, the surfaced adapter files, and an honest readiness scope-down/​verdict.
