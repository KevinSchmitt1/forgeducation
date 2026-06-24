# 13 — Curriculum Planner (Phase 2 / Half B)

**Status:** 🚧 IN PROGRESS (2026-06-24). **Phase 1 (plan-only) implemented** — course data model
(`forged/curriculum/model.py`), course-fidelity union check (`forged/curriculum/fidelity.py`, reusing
an extracted `assess_capability_coverage` core in `pipeline/fidelity.py`), the `curriculum_planner`
persona + `CurriculumPlanner` agent, and `forged course --plan-only`. Validated by
`tests/test_curriculum_model.py`, `test_curriculum_fidelity.py`, `test_curriculum_planner.py`,
`test_cli_course.py` (full suite green; coverage ≥ 80%). Phases 2–5 (orchestration, assembly, reactive
safety net, full CLI) remain. This is **Half B** of the
deliberate two-way split begun in R1 (`11-topic-fidelity-r1.md`). Half A (lesson-level *detect & be
honest*) is merged. Half B is *resolve by decomposing*: turn an over-large topic into an ordered
**course** of module-level lessons instead of silently cutting content. The two halves are coupled by
exactly one thing — the **topic-fidelity signal contract** (R1 Part IV), which this layer consumes.

Target end-state (chosen): **full course assembly** — decompose → orchestrate per-module runs → stitch
into one cohesive course deliverable. The plan below phases toward that so we never bite it whole.

---

## Hand-off — read this first

### Where we are
A single `forged agentic` run produces **one** self-checked lesson notebook. On an over-large topic
("setup **and train** local LLMs on M1") that one lesson cannot honestly hold everything; R1 now makes
any dropped capability **visible** (`TopicFidelitySignal.missing`) instead of silent — but it does not
*resolve* the over-largeness. Resolving it is this layer's job: split the topic into modules
("setup" module + "fine-tuning" module), teach each as its own faithful lesson, and assemble them into
one ordered course.

### The core principle (do not violate)
**Keep the single-lesson pipeline unchanged.** The curriculum planner is a new orchestration layer
*above* `run_pipeline`, not a change to the lesson loop. R1's doc is explicit: folding curriculum
concerns into the lesson loop would multiply the silent-drop defect across every module the planner
spawns. The lesson loop stays the trusted unit; the course layer only *composes* runs and *consumes*
their signals.

### The honesty invariant this layer must guarantee
The **union** of all module capabilities must cover **every** capability of the original topic. The
curriculum planner may *distribute* capabilities across modules; it may never *drop* one. This is the
course-level analogue of the planner's topic-fidelity rule, enforced at two levels:
- **Plan level:** the decomposition persona must account for every requested capability in some module.
- **Run level:** each module run is a normal agentic run, so R1's per-module detector keeps that module
  faithful to its own module spec.

---

## Part I — Design decisions

1. **New layer, not a modified loop.** Add `forged/curriculum/` (planner + orchestrator + assembler)
   and a new CLI verb `forged course`. `run_pipeline` and the lesson personas are untouched.

2. **A course is an ordered set of `TopicSpecification`s.** Each module *is* a `TopicSpecification`
   (`forged/models.py`), so a module run is an ordinary agentic run — maximal reuse, zero new run
   machinery. The course adds only ordering + inter-module prerequisites + course metadata.

3. **Proactive decomposition, with R1 as the safety net.** Decompose *up front* via a new
   `personas/curriculum_planner.md` persona (don't waste a doomed single run first). The reactive R1
   signal (`missing` non-empty after a module run) is the **backstop**: if a module still drops a
   capability, surface it and (optionally) re-decompose that module. Proactive = primary, reactive =
   guardrail — mirrors R1's "personas are the fix, the detector is the backstop" stance.

4. **Decomposition is honest by construction.** The persona's contract is the union invariant above:
   every original capability lands in some module. A deterministic check (course-level fidelity:
   union of module capabilities vs. original topic) backstops the persona, reusing `fidelity.py`'s
   term logic — not a new heuristic family.

5. **Immutable course state.** `CourseSpec`, `ModuleSpec`, `CourseResult`, `ModuleResult` are
   `@dataclass(frozen=True)` with `with_*` builders, identical discipline to `PipelineState`.

6. **Cost is explicit and capped.** N modules = N agentic runs = ~N× the LLM cost of one lesson. This
   is the feature's defining cost. Mitigations are first-class, not afterthoughts (see Part V).

7. **Rich input in, grounded context down — the decomposition is only as good as what it's told.**
   Two halves of one principle:
   - **In:** `forged course` invests in a rich input surface (the full `LearnerProfile` —
     prior_knowledge, constraints, depth — plus a course-level `TopicSpecification` and goals). The
     planner's precision is bounded by input richness, so this is where input effort pays off most.
     (This partially revives the postponed Step 7 question — *does richer input improve quality?* — at
     the course level, where the leverage is largest.)
   - **Down:** the curriculum planner hands each module run the **full lesson-context artifact set the
     R1 agents already consume** (`brief`, `lesson_context`, `topic_spec`) — not a bare topic. Crucially,
     **earlier modules are folded into each later module's prior-knowledge**, so module N's context says
     "the learner has now also covered modules 1…N-1." This kills cross-module redundancy (module 3
     won't re-teach module 1) and materializes the prerequisite chain in the context the agents actually
     read. It also makes the **orientation cell** (doc 12) honest at course scale: module N's "what this
     assumes" can legitimately say "assumes modules 1–2."

   **Split of labour:** the *persona* makes the judgments (decomposition, ordering, per-module depth,
   which earlier modules are prerequisites); the *orchestrator* **deterministically assembles** the
   actual `.md`/`.json` context artifacts from that decision, reusing `build_context_block` — no extra
   LLM call, reproducible, same builder the single-run path uses.

---

## Part II — Patterns to mirror

| Concern | Source | Pattern |
|---|---|---|
| Single-run lifecycle to reuse per module | [cli.py `_cmd_agentic`](../../forged/cli.py#L199-L288) | per-run `run_dir` + `ArtifactStore`; artifacts `brief`/`lesson_context`/`topic_spec`; then SUMMARY/notebook/package writers |
| Run entry point | [graph.py `run_pipeline`](../../forged/pipeline/graph.py) | `run_pipeline(state, store, pipeline, personas_dir, provision)` → final `PipelineState` |
| Signal this layer consumes | [state.py `TopicFidelitySignal`](../../forged/pipeline/state.py#L157) + `PipelineState.topic_fidelity` | frozen value object; `missing` non-empty ⇒ a capability dropped |
| Deterministic fidelity logic to reuse | [fidelity.py `assess_topic_fidelity`](../../forged/pipeline/fidelity.py) | distinctive-term coverage; reuse for course-level union check, no new heuristic |
| Decomposition persona shape | [personas/planner.md](../../personas/planner.md) | the lesson planner, but one altitude up: plan a *course* of lessons, with a topic-fidelity rule |
| Per-run packaging to aggregate | [cli.py `_write_learner_package`](../../forged/cli.py#L406), [report.py](../../forged/report.py), [packaging.py](../../forged/packaging.py) | per-module README/notebook the course index links together |
| Context artifacts handed down per module | [cli.py `_cmd_agentic`](../../forged/cli.py#L258-L269) + [context.py `build_context_block`](../../forged/context.py) | `brief` / `lesson_context` / `topic_spec` seeded into each module store; orchestrator reuses `build_context_block` with prior modules folded into prior-knowledge |
| Prior-knowledge / gap machinery to feed | [personas/planner.md `## Required background & gaps`](../../personas/planner.md#L41-L60) | earlier modules become "Assumed knowledge" for later ones — the same `KNOWN`/`GAP` map, now course-aware |

---

## Part III — Phased implementation plan

Each phase is TDD (RED → GREEN → refactor) and must leave the suite green. CI gates
(`ruff`, `mypy`, `pytest --cov-fail-under=80`) run before any phase is called done. Phases are
independently shippable — stop after any one and the repo is coherent.

### Phase 1 — Course data model + proactive decomposition (plan-only, no orchestration)
- New `forged/curriculum/model.py`: frozen `ModuleSpec` (wraps a `TopicSpecification` + `order` +
  `module_prerequisites: tuple[str, ...]`) and `CourseSpec` (title, ordered `modules`, learner
  profile ref, rationale).
- New `personas/curriculum_planner.md`: given the course brief + learner profile, emit an ordered list
  of modules, each with its own objectives/focus, explicit prerequisite links, and a rationale —
  honoring the **union invariant** (every requested capability lands in a module).
- New `forged/curriculum/planner.py`: thin agent wrapper (mirror `agents/planner.py`) that calls the
  persona and parses the result into a `CourseSpec`.
- Deterministic course-fidelity check (`forged/curriculum/fidelity.py` or extend `fidelity.py`):
  union of module capabilities must cover the original topic; reuse distinctive-term logic.
- CLI: `forged course --plan-only` prints/persists the `CourseSpec` without running anything (the
  cheap, no-LLM-cost-multiplier dry run).
- Tests: model immutability; persona-contract; decomposition parse; union-coverage check (covered,
  dropped-capability → fails honestly).

### Phase 2 — Orchestrate per-module runs (with context hand-down)
- New `forged/curriculum/orchestrator.py`: for each `ModuleSpec` in order, **deterministically assemble
  the handed-down context** (Design decision 7) and seed the module's `ArtifactStore` with
  `brief` / `lesson_context` / `topic_spec` — exactly the artifacts `_cmd_agentic` writes, but with an
  **augmented learner profile**: earlier modules' learning objectives appended to `prior_knowledge` so
  later modules treat them as known. Build `lesson_context` via the existing `build_context_block`.
- Then call the **unchanged** `run_pipeline`, collecting a frozen `ModuleResult` (run_dir, terminal_ok,
  notebook path, `topic_fidelity` signals) into a `CourseResult`.
- Sequential first (simplest, honors cost caps); parallelism is a later optimization, not now.
- Test: module N's seeded `lesson_context` contains modules 1…N-1 as prior knowledge; the same
  `build_context_block` output the single-run path produces (no divergent context builder).
- Reuse the content-addressed venv cache across modules (warm `runs/.venv-cache/*`).
- `--max-modules` cap + explicit per-run cost logging.
- Tests: orchestrator runs N stub modules and aggregates results; a failing module is recorded, not
  silently skipped; `--max-modules` is enforced.

### Phase 3 — Course assembly (the stitch)
- New `forged/curriculum/assembler.py`: write a course directory — an index `README.md` (ordered
  module list, one-line each, prerequisite chain), per-module subdirs, and an aggregate `COURSE.md`
  summarizing each module's outcome + any degradations/fidelity signals.
- Cross-links: each module README links prev/next + its prerequisites.
- Tests: assembler produces an index with correct ordering + links; aggregate surfaces a module's
  degradations.

### Phase 4 — Reactive safety net (wire R1's signal as feedback)
- After each module run, read `ModuleResult.topic_fidelity`. If `missing` is non-empty, the module is
  *still* over-large: record it in `COURSE.md` as a honest course-level warning, and (config-gated)
  re-decompose just that module into sub-modules, bounded by `--max-modules`.
- Tests: a module that drops a capability surfaces a course-level warning; bounded re-decomposition
  terminates.

### Phase 5 — CLI surface + docs close-out
- `forged course --topic … [--learner-profile …] [--plan-only] [--max-modules N] [--no-provision]`.
- Flip this doc to IMPLEMENTED with validating test names; sync `TODO.md` (Phase 2 → in progress/done).
- Run all three CI gates; address reviewer-on-diff findings.

---

## Part IV — Data contracts

```python
@dataclass(frozen=True)
class ModuleSpec:
    spec: TopicSpecification          # a module IS a normal topic → ordinary agentic run
    order: int                        # 0-based position in the course
    module_prerequisites: tuple[str, ...]  # titles of earlier modules this one builds on

@dataclass(frozen=True)
class CourseSpec:
    title: str
    modules: tuple[ModuleSpec, ...]   # ordered
    rationale: str                    # why this decomposition (honesty + audit trail)

@dataclass(frozen=True)
class ModuleResult:
    module: ModuleSpec
    run_dir: str
    terminal_ok: bool
    notebook_path: str | None
    topic_fidelity: tuple[TopicFidelitySignal, ...]   # R1 signal, per module

@dataclass(frozen=True)
class CourseResult:
    course: CourseSpec
    modules: tuple[ModuleResult, ...]
```

**Coupling to R1 (the only one):** this layer reads `PipelineState.topic_fidelity` off each module's
final state. It adds a *course-level* fidelity check (union invariant) but reuses `fidelity.py`'s
term logic — no new heuristic family.

---

## Part V — Cost discipline (the defining risk)

N modules ≈ N× a single lesson's LLM spend (gpt-5 code_author/reviser dominate). Non-negotiable
mitigations, built in from Phase 1:
- **`--plan-only`** (Phase 1) — produce and review the `CourseSpec` for **zero** run cost before
  committing to N paid runs.
- **`--max-modules N`** hard cap (Phase 2) — never fan out unbounded; re-decomposition (Phase 4) is
  bounded by the same cap.
- **Warm venv cache reuse** across modules (Phase 2).
- A real paid+network course run needs user consent and stays to **one** run, like single-lesson E2E.

---

## Part VI — Acceptance

- [ ] `forged course --plan-only` emits an ordered `CourseSpec` whose modules' union covers every
      capability of the original topic (course-fidelity check passes); a decomposition that drops a
      capability fails the check honestly.
- [ ] Per-module orchestration runs each `ModuleSpec` through the **unchanged** `run_pipeline` and
      aggregates a `CourseResult`; a failing module is recorded, never silently skipped.
- [ ] Each module run is seeded with handed-down context (`brief`/`lesson_context`/`topic_spec`) in
      which earlier modules appear as prior knowledge — so later modules don't re-teach earlier ones —
      assembled via the existing `build_context_block` (no divergent context builder).
- [ ] Course assembly writes an ordered index with prerequisite links + an aggregate summary that
      surfaces any module's degradations / fidelity warnings.
- [ ] A module whose run still reports `TopicFidelitySignal.missing` produces a course-level warning
      (and, gated, bounded re-decomposition) — never a silent course-level drop.
- [ ] `--max-modules` enforced; `--plan-only` incurs no LLM run cost.
- [ ] Course state objects are frozen + immutable; CI gates green (`ruff`, `mypy`, coverage ≥ 80%).

---

## Part VII — Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cost multiplication (N× runs) | HIGH | `--plan-only`, `--max-modules`, venv reuse, one-consented E2E (Part V) |
| Decomposition drops/duplicates a capability | MEDIUM | Union-invariant persona rule + deterministic course-fidelity backstop |
| Folding curriculum logic into the lesson loop (defect multiplication) | MEDIUM | Hard architectural boundary: new layer only *composes* runs + *consumes* signals |
| Re-decomposition (Phase 4) loops unbounded | LOW | Bounded by `--max-modules`; off by default |
| Module ordering / prerequisite cycles | LOW | Validate the prerequisite graph is a DAG at plan time |

---

## Scope boundary (Half A vs. Half B)

Lesson level = **detect & be honest** (R1 / doc 11, merged). Course level = **resolve by decomposing**
(this doc). The single coupling is the `TopicFidelitySignal` contract (R1 Part IV), which this layer
consumes — it does **not** modify the lesson loop, the classifier, or the lesson personas.

---

## References
- `docs/architecture/11-topic-fidelity-r1.md` — Half A; Part IV is the consumed signal contract
- `docs/architecture/12-notebook-orientation-cell.md` — sibling honesty feature (input side)
- `forged/pipeline/graph.py` `run_pipeline` — the per-module run entry point
- `forged/cli.py` `_cmd_agentic` — the single-run lifecycle this layer repeats per module
- `forged/pipeline/fidelity.py` — distinctive-term coverage logic reused for the course-level check
- `forged/models.py` `TopicSpecification` — a module is one of these
- `TODO.md` → "Next Major Phase: Phase 2 — Curriculum planner (Half B)"
