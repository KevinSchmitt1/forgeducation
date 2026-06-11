# TODO — forgeducation Input Layer, Agentic Pipeline, & Assessment Redesign

## 🎯 Overall Status

**Phase 1 (Input Specification):** ✅ COMPLETE
- `forged build` supports minimal and structured modes
- 65+ tests passing
- CLI, templates, docs ready

**Migration (Linear → Agentic, LangGraph):** ✅ COMPLETE (Phases 1-9)
- `forged agentic` CLI live; 292 tests passing, 89% coverage
- Both linear and agentic pipelines available for A/B comparison
- See docs/architecture/07-agentic-pipeline-status.md for details

**Current Work:** Step 7 (input-specification testing) is now unblocked

**Roadmap:** Step 7 (testing) → Phase 2 (curriculum planner)

---

## Migration: Linear → Agentic Pipeline (NEW PRIORITY)

**Why:** 
- Step 7 needs to measure agentic vs. linear performance
- Phase 2 (Curriculum Planner) requires agentic routing
- Build once, use twice

**Repo structure:**
```
forged/orchestrator/
├── base.py                    # Shared agent interface (both pipelines use)
├── linear/
│   ├── __init__.py
│   └── orchestrator.py        # Current pipeline (unchanged, baseline)
└── agentic/                   # NEW
    ├── __init__.py
    ├── state.py               # PipelineState schema
    ├── router.py              # Failure classification + routing logic
    ├── nodes.py               # Agent node wrappers
    ├── graph.py               # LangGraph definition
    └── integration.py         # Langfuse instrumentation
```

### Design Phase (IMMEDIATE)

- [ ] Define failure classification categories
  - BLOCKER (structure/logic broken) → back to Planner
  - CODE_QUALITY (compile/runtime errors) → back to CodeAuthor
  - TEST_FAILURE (assertions break) → back to Student/Executor
  - EDGE_CASE (specific inputs break) → back to Student
  - FLAKY (test sometimes passes) → retry or human
  - ACCEPTABLE (minor, move forward) → next stage
  - UNCLASSIFIABLE (can't diagnose) → human review
  
- [ ] Design PipelineState schema
  - `current_stage`, `stage_outputs`, `revisions`, `iteration_counts`
  - Max iterations per stage: 3
  
- [ ] Map routing logic
  - Reviser classifies failure → deterministic routing
  - No vague "confidence" — explicit categories
  - Iteration limits prevent infinite loops

### Implementation Phase (AFTER design)

- [ ] Create `forged/orchestrator/agentic/` structure
- [ ] Implement `state.py` (contracts for everything)
- [ ] Implement `router.py` (routing decisions + failure classification)
- [ ] Wrap agents in `nodes.py` (adapt existing agents for re-callability)
- [ ] Wire LangGraph in `graph.py` (nodes + edges + entry point)
- [ ] Add Langfuse instrumentation in `integration.py`
- [ ] Test both pipelines run without errors
- [ ] Update DEVELOPMENT.md with agentic pipeline guide

---

## Step 7: Input Specification Testing (AFTER migration)

**Status:** 🔄 Deferred until agentic pipeline is ready

**What it measures:**
- Does richer input (minimal vs. medium vs. rich profile) improve output quality?
- How does agentic routing compare to linear?
- Which stages iterate most? Do certain profiles trigger more revisions?

**Test setup:**
- 3 learner profiles (minimal, medium, rich)
- 2 topics (from curriculum)
- 6 total runs (3 × 2)
- Both pipelines: linear baseline + agentic
- Langfuse monitors: iterations, token usage, routing decisions, quality

**Metrics:**
- Iterations per stage (does richer input reduce retries?)
- Routing pattern (which failures get routed back most often?)
- Token usage (agentic vs. linear cost?)
- Final quality (does agentic produce better output?)

**Deliverable:** `tests/input_specification_results.md`

---

## Phase 2: Curriculum Planner (AFTER Step 7)

**Status:** 🔄 Design sketched; implementation deferred until after Step 7

**What it does:**
- Input: topic (e.g., "LLM & Agentic AI")
- Output: module breakdown (Fundamentals → LLMs → Agents → Systems)
- For each module: run agentic pipeline independently

**Uses:** The agentic pipeline we're building now

**Design sketch:**
```
CurriculumPlanner Agent
  ↓ outputs
Module 1 spec → (run agentic pipeline) → Module 1 output
Module 2 spec → (run agentic pipeline) → Module 2 output
Module 3 spec → (run agentic pipeline) → Module 3 output
  ↓ collects
Course output (README + modules + course-manifest.json)
```


---

### Phase 2 Detailed Design

**Pipeline:** Curriculum Planner → (for each module) → Agentic Pipeline
**Output:** Structured course with modules, each with lesson + materials

**Key questions (TBD during Phase 2):**
1. Sequential vs. parallel module generation?
2. How to validate cross-module dependencies?
3. Manifest format for course-level metadata?
4. Learner profile: global or per-module?

**For next dev:**
- Read `docs/architecture/` to understand agent flow
- Start with simple example: "Python" → [Syntax, Data Structures, Functions, OOP]
- Follow the agent pattern in DEVELOPMENT.md
- Test with minimal example before complex topics

---

## Blockers & Dependencies

**Migration (LangGraph):**
- No blockers — can start immediately
- Prerequisite for Step 7 and Phase 2

**Step 7 (Testing):**
- Depends on: Agentic pipeline migration complete
- Provides: Quality baseline for comparison

**Phase 2 (Curriculum Planner):**
- Depends on: Step 7 complete (quality metrics established)
- Uses: Agentic pipeline + Langfuse instrumentation

---

## 📚 References

- **Architecture docs:** `docs/architecture/` (01-input-spec, 02-agent-flow, 03-implementation)
- **Developer guide:** `DEVELOPMENT.md` (how to contribute)
- **User guide:** `templates/README.md` (template usage)
- **History:** `.sessions/` directory (detailed session notes and design decisions)

---

## 📚 References

- **Architecture docs:** `docs/architecture/` (01-input-spec, 02-agent-flow, 03-implementation)
- **Developer guide:** `DEVELOPMENT.md` (how to contribute)
- **User guide:** `templates/README.md` (template usage)
- **History:** `.sessions/` directory (detailed session notes and design decisions)
