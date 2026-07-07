# 16 — Smart Front Door (interactive plan gate)

**Status:** ✅ IMPLEMENTED (2026-07-07). Phases 1–5 shipped on `feat/smart-front-door`; this doc
remains the design of record. Phase 6 close-out (this update, README, TODO/HANDOVER) done in the
same branch. Validating tests per phase are listed in the [Implementation record](#implementation-record).

> Original plan header (2026-07-05): each task was sized small enough for an inexpensive model
> to implement in one sitting, TDD, suite green after every task.

Builds directly on three merged features and changes none of them:
- **Doc 13** — curriculum planner (`forged/curriculum/`): decomposition, union-coverage fidelity
  check, per-module orchestration. This layer *consumes* it.
- **Doc 14 Part III** — the escalation-workflow design ("single smart front door", plan-only by
  default, confirmation before paid runs). This doc *supersedes and extends* that sketch: the
  gate now applies to **both** outcomes (single lesson *and* course) and becomes an interactive
  adjustment loop instead of a plain yes/no.
- **Doc 15** — structured (JSON-schema) grader outputs. The exact same
  `response_format={"type": "json_schema", ...}` posture is reused for the two new/updated LLM
  surfaces here.

---

## Part I — What this is

One command — `forged learn --topic …` — behind which the system decides whether the topic is
one notebook or a course, **always** shows the resulting plan plus a rough cost/time estimate,
and runs **nothing paid** until the user confirms. The user adjusts the plan in natural language
("just make it one notebook", "combine the last two modules"); a small model classifies that
sentence into a structural operation which is applied **deterministically** to the frozen
`CourseSpec` — the plan is never regenerated from scratch for a structural tweak.

### The UX contract

```
$ forged learn --topic "How to set up and train local LLMs on Apple Silicon M1" \
               --learner-profile templates/examples/kevin_learner.yaml

Proposed plan (2 modules):
  [0] Set up a local LLM on Apple Silicon      (objectives: …)
  [1] Fine-tune with LoRA on M1                (objectives: …, builds on: [0])
  Estimated cost: ~$X.XX–$Y.YY  ·  estimated time: ~20–30 min
  Course-fidelity check: ✓ every requested capability is covered

Build this? (yes / no / describe a change) > make it one notebook

Updated plan (1 module):
  [0] Set up and fine-tune a local LLM on Apple Silicon M1
  ⚠ Note: this packs both capabilities into one lesson; if the run cannot honestly
    hold both, the topic-fidelity detector will say so rather than silently dropping one.

Build this? (yes / no / describe a change) > yes
▶ Running 1 module lesson …
```

### Why the gate is unconditional (both branches)

The earlier sketch (doc 14 Part III) gated only the course branch. Gating **both** is simpler
(no "when do we gate?" branch to get wrong) and honest at the seam that matters: the (cheap,
gpt-5-mini) planning happens *before* the gate; the (expensive, gpt-5) code_author/executor loop
happens only *after* confirm. `--yes` restores full automation for scripts.

### Why adjustments are two-tier (the token-overblow guard)

The defining risk of an interactive loop is a user round-trip costing a full re-plan every time.
Structural intent ("1 instead of 2", "merge these", "drop that", "different order") is a **closed
vocabulary** — so:

- **Tier 1 (default, near-zero cost):** a small model sees ONLY the numbered module titles + the
  user's sentence and classifies it into one operation
  (`merge` / `drop` / `force_single` / `reorder` / `confirm` / `cancel`). The operation itself is
  executed as pure Python on the frozen `CourseSpec` — no LLM writes the new plan.
- **Tier 2 (escalation only):** feedback that does not reduce to a structural op (op = `replan`,
  e.g. "module 2 should focus on quantization instead") goes back to the `CurriculumPlanner`
  (gpt-5-mini) with the user's sentence as an explicit guidance line. Still never gpt-5.

After **every** edit — either tier — the deterministic `assess_course_fidelity` union check
re-runs. A user-chosen drop is **warned about, never blocked and never silent** (the user is
allowed to want less; honesty means they are told what they are giving up).

---

## Part II — Design decisions (agreed 2026-07-05, do not relitigate)

1. **New verb `forged learn`; `forged agentic` and `forged course` unchanged.** `agentic`'s
   non-interactive contract is load-bearing (tests, scripts, and `run_course` composing its
   internals). The front door only *composes* existing entry points. `agentic`/`course` remain
   as power-user/internal commands; whether they get deprecated is a later decision, not now.
2. **Sizing = the curriculum planner itself.** `forged learn` always calls `CurriculumPlanner`
   (gpt-5-mini). 1 module returned → single-lesson branch; N modules → course branch. No new
   "readiness" signal, no second sizing heuristic — the planner already owns this judgment
   (its docstring has claimed it since doc 13).
3. **`force_single` = merge-all-and-warn.** Collapse every module into one lesson spec and run
   it. R1's deterministic detector remains the runtime backstop: if one lesson can't honestly
   hold everything, the drop is *surfaced*, not silent. The user overrode the split knowingly;
   we warn, we don't block.
4. **Non-TTY stdin without `--yes` fails fast** (usage error, clear message). A script must
   opt into spending money explicitly; the gate never silently auto-confirms.
5. **The classifier's context is titles-only.** The Tier-1 model never receives full module
   specs, learner profiles, or notebook content — numbered titles + the one user sentence.
   This is the structural guarantee against interactive-loop token growth.
6. **Bounded loop.** `MAX_ADJUSTMENT_ROUNDS` (a named constant, ~10) caps the gate; hitting the
   cap cancels safely (nothing has been spent).

## Part III — Patterns to mirror (with sources)

| Concern | Source | Pattern |
|---|---|---|
| Strict JSON-schema response | `forged/pipeline/agents/student.py` `STUDENT_GRADE_RESPONSE_FORMAT` | same `{"type": "json_schema", "json_schema": {"name": …, "strict": True, "schema": …}}` shape; lenient parse kept as non-OpenAI fallback |
| Thin above-the-loop LLM wrapper | `forged/curriculum/planner.py` `CurriculumPlanner` | no pipeline `Agent` base class; persona file + `LLMClient.complete` + strict parser; injectable `llm_client` for tests |
| Frozen model + pure derivation | `forged/curriculum/model.py` | operations return **new** `CourseSpec`s; renumber `order`; never mutate |
| Persona-contract tests | `tests/pipeline/test_orientation_persona.py`, `test_pedagogy_persona.py` | pin every persona mandate with a test so it can't be silently deleted |
| CLI command shape | `forged/cli.py` `_cmd_course` | input loading + error handling + `EXIT_USAGE`/`EXIT_RUNTIME`/`EXIT_OK` discipline |
| Fidelity recheck | `forged/cli.py` (course cmd) `assess_course_fidelity(list(topic_capabilities(topic_spec)), course)` | re-run after every plan edit |
| Cost estimate inputs | `HANDOVER`-era usage findings: one lesson run ≈ 100K tokens, ~10–12 min typical | constants, clearly labeled rough |

## Part IV — Data contracts

```python
# forged/curriculum/adjuster.py
@dataclass(frozen=True)
class AdjustmentIntent:
    op: str                     # "merge"|"drop"|"force_single"|"reorder"|"replan"|"confirm"|"cancel"
    targets: tuple[int, ...]    # module orders the op applies to (merge: exactly 2; drop: ≥1;
                                # reorder: full permutation; otherwise empty)
    instruction: str            # the user's sentence (verbatim) — used by Tier-2 replan

# forged/curriculum/gate.py
@dataclass(frozen=True)
class GateOutcome:
    confirmed: bool             # True = build it; False = cancelled (incl. round-cap hit)
    course: CourseSpec          # the final (possibly adjusted) plan
    rounds_used: int
```

Operations (`forged/curriculum/operations.py`) are module-level pure functions, not methods —
they belong to the front door, not to the model (`model.py` stays dumb):

```python
def merge_modules(course: CourseSpec, first: int, second: int) -> CourseSpec: ...
def drop_module(course: CourseSpec, target: int) -> tuple[CourseSpec, tuple[str, ...]]: ...
    # returns (new_course, dropped_capabilities) so the caller can warn honestly
def force_single(course: CourseSpec) -> CourseSpec: ...
def reorder_modules(course: CourseSpec, new_order: tuple[int, ...]) -> CourseSpec: ...
    # raises ValueError if a module would precede one of its prerequisites
```

Invariants every operation must uphold (tested):
- Input course is never mutated (frozen + no sneaky list sharing).
- Output modules are renumbered 0..N-1 in their new order.
- `module_prerequisites` references (by title) to removed/merged modules are remapped to the
  surviving/merged title, or dropped when the prerequisite itself was dropped.
- Merging concatenates `learning_objectives` and `focus_areas` (de-duplicated, order-preserving)
  and joins titles ("A + B").

## Part V — Task list (granular; each task = one commit-sized unit, TDD)

Phases are independently shippable; the suite is green after every task. CI gates before any
phase is called done: `.venv/bin/ruff check forged tests` · `.venv/bin/mypy` ·
`.venv/bin/python -m pytest --cov=forged --cov-fail-under=80`.

### Phase 1 — deterministic plan operations (pure Python, zero LLM)
New: `forged/curriculum/operations.py`, `tests/test_curriculum_operations.py`.

- **T1.1 `merge_modules`.** RED: merging modules 1+2 of a 3-module course yields 2 modules,
  orders 0..1, combined objectives/focus areas de-duplicated, title "A + B", prerequisites of
  later modules that referenced either old title now reference the merged title. GREEN: implement.
- **T1.2 `drop_module`.** RED: dropping module 1 of 3 renumbers to 0..1, strips dangling
  prerequisite refs, and returns the dropped module's capabilities. GREEN: implement.
- **T1.3 `force_single`.** RED: any course collapses to exactly 1 module, order 0, no
  module_prerequisites, union of all capabilities, joined title. A 1-module course is returned
  unchanged (same object is fine). GREEN: implement.
- **T1.4 `reorder_modules`.** RED: a valid permutation renumbers correctly; a permutation
  placing a module before its prerequisite raises `ValueError` naming both modules; a
  non-permutation (wrong length, duplicates) raises `ValueError`. GREEN: implement.
- **T1.5 immutability + edge cases.** Original `CourseSpec` object unchanged after every op
  (compare fields, not identity); ops on out-of-range indices raise `ValueError` with the valid
  range in the message.

### Phase 2 — intent classifier (Tier 1)
New: `personas/plan_adjuster.md`, `forged/curriculum/adjuster.py`,
`tests/test_curriculum_adjuster.py`.

- **T2.1 persona.** `personas/plan_adjuster.md`: input is a numbered module-title list + one
  user sentence; output is a single JSON object `{"op", "targets", "instruction"}` — nothing
  else. Mandates to pin: the op vocabulary (`merge`/`drop`/`force_single`/`reorder`/`replan`/
  `confirm`/`cancel`); "when unsure, output replan" (never guess a destructive op); `targets`
  are the shown module numbers; plain agreement words ("yes", "looks good", "ok") → `confirm`;
  refusal ("no", "stop", "cancel") → `cancel`.
- **T2.2 `PlanAdjuster` class.** Mirror `CurriculumPlanner`'s shape exactly (persona load,
  injectable `llm_client`, `DEFAULT_MODEL = "gpt-5-mini"`). `ADJUSTER_RESPONSE_FORMAT`: strict
  schema mirroring `student.py`'s (op as enum, targets as integer array, instruction as string,
  `additionalProperties: False`). `classify(module_titles, sentence) -> AdjustmentIntent`.
  Parse failure or unknown op degrades to `AdjustmentIntent(op="replan", …)` — the safe,
  non-destructive default (same spirit as `graded=false`).
  Tests: schema is forwarded via `response_format`; each op parses; junk degrades to `replan`;
  the user message contains ONLY titles + sentence (assert full specs/objectives absent).
- **T2.3 persona-contract tests.** Same pattern as `test_orientation_persona.py`: assert the
  persona file contains the op vocabulary, the "unsure → replan" rule, and the JSON-only rule.

### Phase 3 — curriculum planner hardening (doc-15 parity + Tier-2 guidance)
Touch: `forged/curriculum/planner.py`, `personas/curriculum_planner.md`,
`tests/test_curriculum_planner.py` (extend).

- **T3.1 structured output.** Add `COURSE_PLAN_RESPONSE_FORMAT` (strict schema: `title`,
  `rationale`, `modules[]` with `title`/`scope`/`depth`/`learning_objectives`/`prerequisites`/
  `focus_areas`/`module_prerequisites`). Pass it in `plan()`'s `complete(...)` call. Keep the
  existing lenient `_extract_json_object` fallback untouched (non-OpenAI providers). Update the
  persona's output section to "JSON object only". Tests: mirror
  `test_structured` assertions used for student/reviewer (format object forwarded; name and
  strict flag correct).
- **T3.2 `guidance` parameter.** `plan(..., guidance: str | None = None)`: when set, append
  a clearly-delimited block to the user message: "Adjustment request from the learner (must be
  honored): …". Persona gains a matching mandate: when an adjustment request is present, change
  ONLY what it asks and keep everything else stable (module count, titles, ordering may change
  only as required by the request). Tests: guidance lands verbatim in the prompt; absent by
  default; persona-contract test pins the stability mandate.

### Phase 4 — the gate loop
New: `forged/curriculum/gate.py`, `tests/test_curriculum_gate.py`.

- **T4.1 estimate + rendering.** Named constants (`EST_TOKENS_PER_LESSON = 100_000`,
  `EST_MINUTES_PER_LESSON = (10, 12)`, cost-per-token constants with a "rough estimate, measured
  2026-06" comment). `render_plan(course, original_capabilities) -> str`: numbered modules with
  one-line objectives + builds-on links, the estimate scaled by module count, and the current
  fidelity check result (✓ / ⚠ with the missing capabilities listed). Pure function, tested on
  string content.
- **T4.2 `run_gate`.** Signature:
  `run_gate(course, original_capabilities, adjuster, replanner, input_stream, output_stream, max_rounds=MAX_ADJUSTMENT_ROUNDS) -> GateOutcome`.
  Loop: render → prompt `Build this? (yes / no / describe a change) >` → read line → classify
  via adjuster → dispatch:
  - `confirm` → return confirmed outcome; `cancel` → return cancelled outcome;
  - `merge`/`drop`/`force_single`/`reorder` → apply the pure op (T1.x); `ValueError` from an op
    (bad targets) → print the error, re-prompt, does NOT consume a round? No — **counts** as a
    round (simplest; the cap exists to terminate);
  - `replan` → call `replanner(course, instruction)` (a callable so tests inject a stub; CLI
    wires it to `CurriculumPlanner.plan(..., guidance=…)`); planner exception → print error,
    keep the current plan, continue;
  - after every successful edit: re-run fidelity vs. `original_capabilities`; on regression print
    the ⚠ line with exactly what is now missing (drop/force_single warnings included here).
  - EOF on input or `max_rounds` reached → cancelled outcome (nothing spent, say so).
  Tests (scripted StringIO conversations): confirm-first-try; merge-then-confirm; force_single
  shows the fidelity warning; drop reports dropped capabilities; replan path calls the injected
  replanner with the verbatim sentence; op ValueError re-prompts; round cap terminates cancelled;
  EOF terminates cancelled.

### Phase 5 — CLI wiring
Touch: `forged/cli.py`; new `tests/test_cli_learn.py`.

- **T5.1 `_cmd_learn`.** Mirror `_cmd_course`'s load block (topic/profile/spec/pipeline, same
  error handling). Then: `CurriculumPlanner.plan` → if `--yes`: skip the gate (plan is accepted
  as-is, still printed); else if stdin is not a TTY: print "interactive gate needs a TTY; pass
  --yes to run non-interactively" → `EXIT_USAGE`; else `run_gate(...)` with the real
  stdin/stdout and a replanner closure over the planner. Cancelled → print "nothing was run",
  `EXIT_OK` (a deliberate no is a success, not an error). Confirmed:
  - 1 module → single-lesson branch: reuse the module's `TopicSpecification` and the existing
    single-run path (same lifecycle `_cmd_agentic` uses) under `runs/<stamp>_<slug>/`;
  - N modules → `run_course(...)` exactly as `_cmd_course` does (persist plan, `--max-modules`,
    `--no-provision`, `_report_course_result`).
- **T5.2 subparser.** `forged learn --topic … [--learner-profile … --topic-spec … --yes
  --max-modules N --no-provision --runs DIR --personas DIR --config NAME --debug]` — flag names
  identical to the existing commands. Help text: "One front door: plan first, confirm, then
  build a lesson or a course."
- **T5.3 CLI tests.** Mocked `CurriculumPlanner` + scripted streams: 1-module confirm → the
  single-lesson path is invoked (patched); N-module confirm → `run_course` invoked; `--yes`
  skips prompting; non-TTY without `--yes` → `EXIT_USAGE`; cancel → `EXIT_OK`, no run invoked.

### Phase 6 — close-out
- Flip this doc to IMPLEMENTED with the validating test names per phase.
- README: document `forged learn` as the primary entry point (the "one front door" story);
  `agentic`/`course` remain documented as direct/advanced commands.
- Sync `TODO.md` + `HANDOVER.md`; delete stale branches; all three CI gates; reviewer-on-diff;
  branch + PR (never straight to master).

## Part VI — Cost & safety analysis

| Surface | Model | Context size | When |
|---|---|---|---|
| Sizing/decomposition | gpt-5-mini | brief + learner context (existing) | once per `forged learn` |
| Intent classification | gpt-5-mini | module titles + one sentence (~100 tokens) | once per adjustment round |
| Tier-2 replan | gpt-5-mini | brief + context + guidance line | only when feedback isn't structural |
| Lesson build(s) | gpt-5 (+mini critics) | full pipeline | **only after explicit confirm / --yes** |

Worst case pre-confirm (10 rounds, all replans) ≈ 11 gpt-5-mini calls — still a fraction of one
gpt-5 code_author call. The expensive loop cannot start without confirm; a cancelled gate costs
only the initial decomposition.

## Part VII — Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Classifier misreads intent → wrong structural edit | MEDIUM | every edit re-rendered before anything runs; user corrects or cancels; "unsure → replan" persona rule avoids destructive guesses |
| Merge/force_single yields an over-large module | MEDIUM | fidelity recheck at the gate + R1 detector at runtime — surfaced, never silent |
| Interactive code hard to test | LOW | streams + replanner injected; zero real-TTY tests |
| Divergence between `learn`'s single-lesson branch and `_cmd_agentic` | MEDIUM | reuse the same writers/entry points; the known deliverable-writer extraction (doc 13 gap) reduces this further when done |
| Pre-existing flaky integration tests muddy CI signal | MEDIUM | tracked separately (see TODO); all new tests here are unit-level |

## Part VIII — Acceptance

- [ ] `forged learn` with a small topic proposes 1 module; with an over-large topic proposes N.
- [ ] Nothing paid runs before confirm; `--yes` skips the gate; non-TTY without `--yes` is a
      usage error; cancel exits 0 having run nothing.
- [ ] "make it one notebook" / "combine 1 and 2" / "drop module 3" / "swap 2 and 3" each apply
      the right deterministic op — no re-plan call — and the plan re-renders with a fidelity
      re-check; non-structural feedback triggers exactly one guided gpt-5-mini re-plan.
- [ ] Any capability lost by an edit is printed at the gate; a confirmed course/lesson then
      behaves exactly like today's `forged course` / single-run paths (R1, orientation,
      readiness all still apply — this layer changes none of them).
- [ ] `CurriculumPlanner` requests strict structured output on OpenAI (doc-15 parity), lenient
      fallback preserved.
- [ ] All state frozen; ops pure; CI gates green (ruff, mypy, coverage ≥ 80%).

## Implementation record

Shipped 2026-07-07 on `feat/smart-front-door`, one commit per phase, all TDD.

| Phase | Code | Validating tests |
|---|---|---|
| 1 — plan operations | `forged/curriculum/operations.py` (`merge_modules`/`drop_module`/`force_single`/`reorder_modules`) | `tests/test_curriculum_operations.py` (23) |
| 2 — intent classifier | `personas/plan_adjuster.md`, `forged/curriculum/adjuster.py` (`PlanAdjuster`, `AdjustmentIntent`, `ADJUSTER_RESPONSE_FORMAT`) | `tests/test_curriculum_adjuster.py` (20) |
| 3 — planner hardening | `forged/curriculum/planner.py` (`COURSE_PLAN_RESPONSE_FORMAT`, `plan(..., guidance=…)`), `personas/curriculum_planner.md` | `tests/test_curriculum_planner.py` (structured-format + guidance + persona-contract) |
| 4 — the gate loop | `forged/curriculum/gate.py` (`render_plan`, `run_gate`, `GateOutcome`, `MAX_ADJUSTMENT_ROUNDS`) | `tests/test_curriculum_gate.py` (15) |
| 5 — CLI wiring | `forged/cli.py` (`_cmd_learn`, `_run_plan_gate`, `_build_confirmed`, `_run_agentic_lesson` extraction, `learn` subparser) | `tests/test_cli_learn.py` (7) |

Notes for the next reader:
- The single-lesson branch reuses `_run_agentic_lesson` (extracted from `_cmd_agentic`), so a
  1-module `forged learn` produces exactly the `forged agentic` deliverables. This is a partial
  down-payment on the still-owed deliverable-writer extraction — `_write_agentic_summary` /
  `_write_final_notebook` / `_write_learner_package` remain in `cli.py`.
- Still owed (unchanged by this work): a **paid live `forged learn`** smoke run (1-module topic to
  exercise the real gate → single-lesson path; then a small course), and the deliverable-writer
  module extraction.

## References

- `docs/architecture/13-curriculum-planner.md` — the layer this composes (Phases 3–5 still open)
- `docs/architecture/14-code-explanation-and-readiness.md` — Part III sketch this supersedes
- `docs/architecture/15-structured-grader-output.md` — the response_format posture reused here
- `forged/curriculum/planner.py`, `model.py`, `fidelity.py` — existing curriculum layer
- `forged/pipeline/agents/student.py` — the strict-schema pattern to mirror
- `forged/cli.py` `_cmd_course` / `_cmd_agentic` — the entry points the front door composes
