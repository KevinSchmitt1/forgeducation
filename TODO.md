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

### 🔄 Current Work

- **Step 7: Input-specification testing**
  - now unblocked
  - should compare richer structured input against minimal input
  - should compare linear vs. agentic quality/cost/iteration behavior

### ⏭ Next Major Phase

- **Phase 2: Curriculum planner**
  - depends on Step 7 results
  - will orchestrate multiple module-level agentic runs into one course output

---

## Step 7: Input Specification Testing

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

**Status:** design sketched; implementation deferred until after Step 7

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
2. How to validate cross-module dependencies and ordering?
3. What should the course-level manifest contract be?
4. Should learner profile stay global or allow per-module overrides?

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
