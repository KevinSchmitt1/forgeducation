# TODO — forgeducation Roadmap

## Current Status

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

### ⏭ Next Major Phase

- **Phase 2: Curriculum planner (Half B)** — orchestrates multiple module-level agentic runs into
  one course. **R1 (Half A) is now done**, so the foundation is in place: consume the
  `TopicFidelitySignal` (`forged/pipeline/fidelity.py`, recorded on `PipelineState.topic_fidelity`)
  so an over-large topic is decomposed into modules instead of silently cut. See "R1 — Topic
  Fidelity" below and `docs/architecture/11-topic-fidelity-r1.md` → Part IV for the signal contract.

---

## R1 — Topic Fidelity (the cut-off mandatory topic) — TOP PRIORITY

**Problem.** On topic *"setup AND train local LLMs"*, the agentic loop produced a well-explained
notebook that **silently dropped LoRA fine-tuning** across iterations: a content-scoped explanation
gap was mis-tagged `[BLOCKER/plan]`, which triggered a replan that descoped instead of scaffolding.
Full spec, fix direction, and acceptance: `docs/architecture/10-output-quality-remediation.md` → **Part IX / R1**.

**Two layers — fix detection now, resolve via the curriculum planner later:**

1. **Lesson level (do now).** The loop must never *silently* drop a capability named in the `--topic`.
   - Sharpen the Student/Reviewer scope rubric (an under-explained-but-correct step is `content`, not a
     `plan` BLOCKER) so explanation gaps stop triggering descoping replans.
   - Anchor the planner to the brief on replan + add a topic-fidelity check, so any genuine descope is
     **reported honestly** (recorded signal / non-acceptable), never hidden.

2. **Curriculum planner (Phase 2 — Kevin's brainstorm).** Once descoping is *visible*, the curriculum
   planner is the right place to *resolve* an over-large topic: decompose it into modules so the cut
   content becomes its own lesson (setup module + fine-tuning module) or is handed to a sibling
   notebook, rather than being lost. R1's signal is the trigger for that decomposition.

**Keep R1 and the curriculum planner separate** (tracked + implemented independently). Do **not** fold
R1 into Phase 2 — the silent-drop defect would otherwise be multiplied across every module the planner
spawns. Fix the lesson-level detection/honesty first (it's the foundation), and design the
topic-fidelity signal as a reusable contract Phase 2 *consumes* for module splitting. The only coupling
is that signal. Division of labour: lesson level = **detect & be honest** (R1, here); curriculum level
= **resolve by decomposing** (Phase 2). See the matching "Scope boundary" note in
`docs/architecture/10-output-quality-remediation.md` → Part IX / R1.

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
- [ ] Surface trace ids / trace URLs in run summaries or manifests
- [ ] Compare outcome quality across model mixes

**References:** `docs/architecture/08-stage-specific-models.md`, `docs/architecture/09-langfuse-tracing.md`

---

## Phase 2: Curriculum Planner

**Status:** design sketched; implementation gated on **R1** (topic-fidelity foundation). Step 7 is
postponed, so Phase 2 no longer waits on it — but it should consume R1's topic-fidelity signal so an
over-large topic is decomposed into modules instead of silently cut (see "R1 — Topic Fidelity").

**What it does:**

- Input: broad topic area (for example, `LLM & Agentic AI`)
- Output: module breakdown plus one agentic lesson pipeline per module
- Final output: course-level README/manifest plus module artifacts

**Design sketch:**

```text
CurriculumPlanner Agent
  ↓ outputs
Module 1 spec → agentic pipeline → Module 1 output
Module 2 spec → agentic pipeline → Module 2 output
Module 3 spec → agentic pipeline → Module 3 output
  ↓ collects
Course output (README + modules + course-manifest.json)
```

**Open design questions:**

1. Sequential vs. parallel module generation?
2. How to validate cross-module dependencies and ordering? --> maybe the planner does it first and the both reviewers (student and expert) analyse, if all the topics taught are present in the full curriculum/covered by other notebooks
3. What should the course-level manifest contract be?
4. Should learner profile stay global or allow per-module overrides? --> it could override, since the learner learns consecutively in the notebooks

---

## Dependencies

- **Step 7** depends on the completed agentic pipeline and benefits from the new stage-specific model configuration.
- **Further observability follow-up** depends on the current Langfuse wiring and should focus next on linking run artifacts back to traces.
- **Phase 2** depends on Step 7 establishing a quality/cost baseline.

---

## References

- `docs/architecture/07-agentic-pipeline-status.md` — current implemented agentic pipeline
- `docs/architecture/08-stage-specific-models.md` — current model-resolution design and defaults
- `docs/architecture/09-langfuse-tracing.md` — current tracing implementation and caveats
- `DEVELOPMENT.md` — contributor-oriented map of the codebase
- `templates/README.md` — user-facing structured input guide
