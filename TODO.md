# TODO — forgeducation Roadmap

> **▶ Resuming work? Read [`HANDOVER.md`](HANDOVER.md) first** — it's the cold-start brief: current
> state, the open next-task fork (curriculum Phases 3–5 vs. doc 14 Part III), files needed, and open
> discussion items.

## Current Status


## Add a real section to work with all the .md files in the agentic workflow (e.g. update all documents after work and so on)

### ✅ Complete

- **Phase 1: Input specification**
  - `forged build` supports minimal and structured modes
  - learner profile + topic specification templates are implemented
  - CLI, templates, and architecture docs are in place

- **Agentic migration (Phases 1–9)**
  - LangGraph-based agentic pipeline is implemented under `forged/pipeline/`
  - `forged agentic` CLI is live
  - executor, routing, revision briefs, and deterministic reviser are working
  - see `docs/architecture/07-agentic-pipeline-status.md`

- **Stage-specific model configuration**
  - linear and agentic paths now resolve models through shared config
  - bundled pipeline YAML includes stage-specific defaults
  - see `docs/architecture/08-stage-specific-models.md`

- **Output-quality remediation (Phases 1–6)**
  - honest signals + rubric grading + anti-hollow structural gate
  - self-contained deliverable: per-run `README.md` + `requirements.txt`
  - real LLM content reviser as the `CONTENT_QUALITY` target
  - default environment provisioning + content-addressed venv cache (`--no-provision` opts out)
  - validated by a real run on the original "local LLMs on Apple Silicon" topic
  - see `docs/architecture/10-output-quality-remediation.md`

- **Agentic reviewer critic + learner-aligned explanations + runnable-kernel packaging** (PR #5)
  - second critic added (expert correctness/quality): `student → reviewer → revisor`; the
    reviser merges both critics' findings before classifying
  - personas teach prerequisite gaps from first principles and treat explanation cells as a
    first-class deliverable (`material_density` now drives explanation depth)
  - learner `requirements.txt` includes `ipykernel`; README documents kernel registration
  - **surfaced R1** (topic descoping) — now the top open task; see below

### ✅ Recently Completed

- **Structured (JSON-schema) grader outputs.** Student and Reviewer now request OpenAI
  `response_format={"type": "json_schema", ...}` via `LLMClient.complete(...)` instead of relying on
  prompt discipline ("prose, then a trailing JSON block"). Closes the failure mode where a paid run
  completed planner → code_author → executor → provisioning and then lost the quality judgment to an
  unparseable critic response. Ollama/local providers omit `response_format` and keep the existing
  lenient parser as a fallback. See `docs/architecture/15-structured-grader-output.md`.

- **Code maps, cell briefs, and the planner readiness verdict (doc 14, Parts I–II).** A real run on a
  dense ML topic surfaced two gaps the existing honesty machinery didn't catch: (1) a "concept→code
  cliff" — LoRA was explained conceptually, then the learner was dropped into an unexplained
  `LoraConfig(...)` call; (2) silent artifacts — a real trained adapter was written to disk with no
  notice. Fixed via persona-only changes: `code_author` now emits an ASCII pipeline map plus per-cell
  "decode-the-call" briefs for dense/new-construct cells, and must surface what any file-writing cell
  produced; `student`/`reviewer` enforce it as a `content`-scope fix (never an amputating
  `plan`/`structure` BLOCKER). The planner also gained a **readiness verdict**: when prerequisite gaps
  are foundational and too deep for one honest lesson, it scopes to a teachable beachhead and declares
  the rest a `TopicFidelitySignal` gap rather than cramming. This is the fourth honesty rule (after R1,
  orientation, curriculum): **don't silently cram a topic past the learner's foundation.**
  **Part III (escalation workflow) is designed but not built** — see
  `docs/architecture/14-code-explanation-and-readiness.md`.

- **Curriculum planner (Half B) — Phases 1–2.** A new orchestration layer *above* the unchanged
  lesson loop that decomposes an over-large topic into an ordered course of module lessons and runs
  each module. Plan + status: `docs/architecture/13-curriculum-planner.md`.
  - **Phase 1 (plan-only):** `forged/curriculum/` — frozen `CourseSpec`/`ModuleSpec`; `CurriculumPlanner`
    (persona `personas/curriculum_planner.md`, defaults to **gpt-5-mini**) decomposes a brief into an
    ordered course; `assess_course_fidelity` enforces the union-coverage honesty invariant (the union of
    module capabilities must cover every requested capability — distribute, never drop), reusing R1's
    term logic. `forged course --plan-only [--out DIR]` (persists `course_plan.json` + `COURSE.md`).
  - **Phase 2 (orchestration):** `run_course` runs each module through the **unchanged** `run_pipeline`
    with the **context hand-down** — `_augment_profile` folds earlier modules' objectives into a later
    module's `prior_knowledge` (immutable), seeded via the same `build_context_block` the single-run path
    uses, so module N is never re-taught modules 1…N-1. Frozen `ModuleResult`/`CourseResult`; failing
    modules recorded never skipped; sequential (parallel deferred). `forged course` (no `--plan-only`)
    runs the course under `runs/<stamp>_course_<slug>/` with `--max-modules`/`--no-provision`.
  - **Validated:** real plan-only runs on the local-LLM topic (2-module split) and an overarching course
    (6-module DAG); full suite green. **Known gap:** per-module deliverable writers reused from `cli` via
    a deferred import, patched out in unit tests — real writing runs only live (extraction is a follow-up).

- **Learner orientation cell ("Start Here").** The accepted notebook opened with a topic summary in
  its own jargon, so a learner missing the prerequisites was lost at cell 0 — even though the Planner
  already computes a per-learner `KNOWN`/`GAP` map that never reached the learner. Fix (persona-only,
  Planner + Code Author): the first markdown cell is now a learner **orientation** — plain-language
  goal, a jargon-free two-facet roadmap (*what it does* + *what you should understand afterward*,
  plain-first with real terms in parentheses), and "what this assumes / your likely gap" surfaced from
  the gap map. Gated to one line when there are no gaps. R1's input-side twin: R1 = honest about
  *output*; this = honest about *assumed input*. Plan + close-out:
  `docs/architecture/12-notebook-orientation-cell.md`; validated by
  `tests/pipeline/test_orientation_persona.py`. Phase 3 deterministic backstop deferred (YAGNI).

- **R1 — topic fidelity, lesson level (Half A).** The agentic revision loop could silently drop a
  capability the `--topic` requested (it shipped "setup local LLMs" for a "setup *and train*" topic).
  Fixed at the lesson level: **detect & be honest**. Plan + close-out:
  `docs/architecture/11-topic-fidelity-r1.md`.
  - Student/Reviewer scope rubric sharpened: an under-explained-but-correct, executing step is
    `content` (scaffold), never a `plan`/`structure` BLOCKER (amputate).
  - Planner anchored to the brief on replan: keep every requested capability, or declare
    infeasibility honestly — never silently substitute an easier lesson.
  - Deterministic topic-fidelity detector (`forged/pipeline/fidelity.py`) emits a
    **`TopicFidelitySignal`** recorded on state + surfaced in `SUMMARY.md`, so a descope is never
    silent. **This signal is the reusable contract Phase 2 consumes** (the only R1↔Phase-2 coupling).
  - `topic_spec.json` now persisted at CLI setup as the detector's structured input.

### ⏭ Postponed

- **Step 7: Input-specification testing — POSTPONED behind R1** (was "now unblocked").
  Deferred because R1 matters more right now. The linear-vs-agentic comparison is dropped — we
  only ship the agentic pipeline. Detail retained below.

### ✅ DONE (2026-07-07): the Smart Front Door (doc 16)

**Shipped on `feat/smart-front-door`** (Phases 1–5, one commit per phase, TDD): one `forged learn`
command; the CurriculumPlanner sizes single-lesson vs. course; an **unconditional interactive
confirmation gate** runs nothing paid until the learner confirms; natural-language plan adjustments
are classified by a small model (`PlanAdjuster`) into deterministic `CourseSpec` operations
(`merge`/`drop`/`force_single`/`reorder`), with a guided gpt-5-mini re-plan as the only escalation.
`--yes` skips the gate; a non-TTY stdin without `--yes` is a usage error. Doc 16 flipped to
IMPLEMENTED with the validating test names; README updated to lead with `forged learn`.

**Still owed for this feature** (carried below, unchanged): the deliverable-writer extraction and a
**paid live `forged learn` smoke run** (1-module topic → single-lesson path; then a small course).

---

### ⏭ Next Up — the queued fork (Option A remains)

The 2026-07-05 fork resolved to the smart front door (now done). What remains queued:

**Option A — Curriculum planner Phases 3–5.** The curriculum planner can now plan and run a course.
What remains (see `docs/architecture/13-curriculum-planner.md` Phases 3–5):

- **Phase 3 — course assembly.** Stitch the per-module outputs into one course: an index `README.md`
  (ordered modules, prerequisite cross-links) + aggregate `COURSE.md` surfacing each module's
  degradations / fidelity signals.
- **Phase 4 — reactive safety net (the R1 → planner → R1 loop).** When a module run still drops a
  capability (`ModuleResult.topic_fidelity.missing`), hand the overflow back to the curriculum planner
  as a new module and run it; bounded by `--max-modules`. (Kevin's framing.)
- **Phase 5 — close-out.** Flip doc 13 to IMPLEMENTED; full CLI polish.

**Option B — Doc 14 Part III: escalation workflow.** See
`docs/architecture/14-code-explanation-and-readiness.md` Part III. Wires the planner's readiness
verdict into an automatic route: `forged agentic` runs the planner → if the verdict is "gap too deep,"
it does not build a single lesson — it calls the curriculum planner for a course plan, shows the
learner the preview (`COURSE.md` + rough cost/time), and **stops**, asking for explicit confirmation
before any paid build (a `--yes` flag skips the prompt for automation). Reuses everything already
merged (readiness verdict + `forged course --plan-only` + curriculum decomposition); the new pieces
are only the auto-route on the verdict and the confirmation gate. This is also the natural home for
Option A's Phase 4 (reactive re-decomposition shares the same machinery), so building B first doesn't
strand A's later work.

**Regardless of which is picked:**
- **Cleanup (known gap):** extract `forged.cli`'s per-run deliverable writers
  (`_write_agentic_summary`/`_write_final_notebook`/`_write_learner_package`) into a shared module so
  the orchestrator needn't reach into `cli` via a deferred import.
- **Live validation (paid):** a real full course run (N module pipelines) — needs consent + cost
  (~$10–25, 1–3h for the 6-module course). Suggested first step: a single-module smoke test
  (`forged course … --max-modules 1 --no-provision`).

---

## ✅ R1 — Topic Fidelity (the cut-off mandatory topic) — DONE

**Shipped** (lesson-level "detect & be honest"; see Recently Completed above and
`docs/architecture/11-topic-fidelity-r1.md`). Its `TopicFidelitySignal` is the reusable contract the
curriculum planner (Half B) now consumes. Historical context retained below.

**Problem (now fixed).** On topic *"setup AND train local LLMs"*, the agentic loop produced a
well-explained notebook that **silently dropped LoRA fine-tuning** across iterations: a content-scoped
explanation gap was mis-tagged `[BLOCKER/plan]`, which triggered a replan that descoped instead of
scaffolding. Full spec: `docs/architecture/10-output-quality-remediation.md` → **Part IX / R1**.

Division of labour (both halves now done): lesson level = **detect & be honest** (R1); curriculum
level = **resolve by decomposing** (curriculum planner, above).

---

## Step 7: Input Specification Testing — POSTPONED (behind R1)

**Goal:** measure whether richer structured input improves lesson quality enough to justify the extra input burden.

**Questions to answer:**

- Does richer learner/topic context improve final notebook quality?
- Does it reduce revision loops or reroutes?
- Does agentic routing outperform the linear baseline on the same inputs?
- Which stages become the main token/cost drivers once richer context is used?

**Suggested test matrix:**

- 3 learner-profile richness levels: minimal, medium, rich
- 2 topics from the intended curriculum surface
- 2 execution paths: linear and agentic

**Suggested metrics:**

- final quality score
- accepted vs. non-accepted runs
- iteration count / reroute count
- per-stage token or model usage
- total runtime
- total cost

**Desired deliverable:**

- `tests/input_specification_results.md`

---

## Observability Follow-Up

**Status:** partially complete

**Goal:** make model/version comparisons observable per run and per stage.

### Planned work

- [x] Add Langfuse instrumentation for every LLM-backed agent prompt
- [x] Record resolved `provider` + `model` at the tracing layer for each generation
- [x] **Per-call token usage → `usage.json` + `USAGE.md` per run** (PR #13). Captures input / output /
  **cached-input** / **reasoning** tokens per stage via a ledger inside `LLMClient.complete`. Offline,
  provider-agnostic; replaces guesswork about run cost. See `forged/usage.py`.
- [ ] Surface trace ids / trace URLs in run summaries or manifests
- [ ] Compare outcome quality across model mixes
- [ ] (gap) Meter empty/length-truncated calls too — they raise before usage records, so failed-but-billed
  calls aren't counted.

### Cost findings (live R1 run `localLLM_tokens_last`, 11 calls / 102K tokens)

The bill is **output/reasoning-dominated**, not input-dominated (this reverses the earlier
"caching is #1" assumption). Levers, highest-impact first:

- **Cut gpt-5 reasoning** — reasoning ≈ 30% of a run (31K tokens; 17K on `code_author` alone).
  `forged/llm.py` doesn't set OpenAI `reasoning_effort`; a low setting on `code_author`/`reviser` is the
  biggest controllable lever.
- **Restructure critic prompts for caching** — `code_author` already caches **47.5%** of input; the
  critic stages cache **0%**. Put the stable prefix (persona + context) first, volatile notebook last.
- **API-drift hardening** — the run produced a *real* LoRA adapter on `distilgpt2` but failed on
  `TrainingArguments(evaluation_strategy=…)` (renamed to `eval_strategy` in recent `transformers`);
  code_author exhausted its fix budget. Pin `transformers` in the planner's `requirements` and/or teach
  code_author the rename.
- **Parked:** subscription/Claude-Pro path (no programmatic access; worse fit for an output-heavy bill)
  and local Ollama routing (8 GB M1 can't run it; can't do the expensive stage anyway).

**References:** `docs/architecture/08-stage-specific-models.md`, `docs/architecture/09-langfuse-tracing.md`,
`forged/usage.py`

---

## Curriculum Planner (Half B) — design questions still open for Phases 3–5

**Status:** Phases 1–2 **implemented** (plan + orchestrate; see Recently Completed and
`docs/architecture/13-curriculum-planner.md`). The decisions below were resolved during build; the
remaining open questions belong to Phases 3–5.

**Resolved during Phases 1–2:**

1. **Sequential vs. parallel?** Sequential now; dependency-aware parallel deferred (the modules form a
   DAG, and because only *objectives* are folded into prior knowledge there is no hard data dependency
   forcing strict order — so parallel is feasible later). See doc 13 Part I.b.
2. **Learner profile global or per-module?** Per-module **augmentation** — each later module's profile
   gains earlier modules' objectives as prior knowledge (the context hand-down), so the learner "learns
   consecutively." Base profile never mutated.
3. **Cross-module coverage validation.** Deterministic `assess_course_fidelity` (union-coverage) checks
   the plan covers every requested capability before any run.

**Still open (Phases 3–5):**

1. Course-level manifest/index contract (Phase 3 assembly).
2. Reactive re-decomposition policy + bounds when a module is still over-large (Phase 4).
3. When (if ever) to turn on parallel module execution.

---

## Dependencies

- **Curriculum planner Phases 3–5** build on the merged Phases 1–2 (no external gate).
- **Step 7 (postponed)** depends on the completed agentic pipeline; lower priority than the curriculum
  planner follow-ups.
- **Observability follow-up** depends on the current Langfuse wiring; next focus is linking run
  artifacts back to traces.

---

## References

- `docs/architecture/07-agentic-pipeline-status.md` — current implemented agentic pipeline
- `docs/architecture/08-stage-specific-models.md` — current model-resolution design and defaults
- `docs/architecture/09-langfuse-tracing.md` — current tracing implementation and caveats
- `docs/architecture/11-topic-fidelity-r1.md` — R1 (topic fidelity, Half A) — DONE
- `docs/architecture/12-notebook-orientation-cell.md` — learner orientation cell — DONE
- `docs/architecture/13-curriculum-planner.md` — curriculum planner (Half B) — Phases 1–2 done
- `docs/architecture/14-code-explanation-and-readiness.md` — code maps, cell briefs, readiness
  verdict — Parts I–II done, Part III (escalation workflow) designed, not built
- `docs/architecture/15-structured-grader-output.md` — structured (JSON-schema) grader outputs — done
- `DEVELOPMENT.md` — contributor-oriented map of the codebase
- `templates/README.md` — user-facing structured input guide
