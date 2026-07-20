# 13 — Curriculum Planner (Phase 2 / Half B)

**Status:** 🚧 IN PROGRESS (2026-07-20). **Phases 1, 2, 3, 4 implemented**; Phase 5
(CLI surface + docs close-out) remains. **Phase 1 (plan-only) implemented** — course data model
(`forged/curriculum/model.py`), course-fidelity union check (`forged/curriculum/fidelity.py`, reusing
an extracted `assess_capability_coverage` core in `pipeline/fidelity.py`), the `curriculum_planner`
persona + `CurriculumPlanner` agent (defaults to **gpt-5-mini** — gpt-4o-mini gave coarser splits),
and `forged course --plan-only [--out DIR]` (persists `course_plan.json` + `COURSE.md`).

**Phase 2 (orchestration) implemented** — `forged/curriculum/orchestrator.py::run_course` runs each
module through the **unchanged** `run_pipeline`, with the context hand-down (Design decision 7):
`_augment_profile` folds earlier modules' objectives into a later module's `prior_knowledge` (immutable
`dataclasses.replace`), then seeds `brief`/`lesson_context`/`topic_spec` via the **same**
`build_context_block` the single-run path uses. Frozen `ModuleResult`/`CourseResult`; failing modules
recorded never skipped; sequential (parallel deferred); `forged course` (no `--plan-only`) runs the
course under `runs/<stamp>_course_<slug>/` with `--max-modules`/`--no-provision`. Validated by
`tests/test_curriculum_*.py` + `test_cli_course.py` (full suite green; coverage ≥ 80%).

> **Known gap:** `_write_module_deliverables` reaches into `forged.cli` private writers via a deferred
> import (avoids a load cycle) and is patched out in unit tests — the real per-module SUMMARY/notebook/
> package writing is only exercised in a live run. Follow-up: extract those writers to a shared module.

**Phase 4 (reactive safety net) implemented** (2026-07-12) — see the Phase 4 section below; it shipped
ahead of Phase 3 because it only composes existing runs + the planner, needing no assembler.
**Phase 3 (course assembly) implemented** (2026-07-20) — see the Phase 3 section below. Phase 5
(close-out) remains. This is **Half B** of the
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

## Part I.b — Execution model: sequential now, dependency-aware parallel later

Empirically (gpt-5-mini decomposition of the overarching local-LLM brief), the modules form a
**DAG, not a chain** — e.g. "serving" depends on both "RAG" and "quantization". So the execution
model is a real choice:

- **Start sequential (Phase 2).** Simplest; bounds cost (one paid run at a time vs. an N× concurrent
  spike); and it keeps the reactive re-decomposition loop (Phase 4) tractable, since that loop mutates
  the course graph mid-flight and naive parallelism would race it.
- **Parallelism is feasible later, by DAG level.** Key insight: the context hand-down folds earlier
  modules' **objectives** (known at *plan* time) into prior knowledge — **not** their generated
  notebooks. So there is no hard *data* dependency forcing strict order; the prerequisite edges are
  *pedagogical ordering*. Modules whose prerequisites are all satisfied can therefore run concurrently.
- **Why not parallel first:** (1) cost — N concurrent gpt-5 runs is an unbounded spike and provisioning
  N venvs contends on disk/network; (2) the Phase-4 reactive loop changes the graph as it runs.
- **Decision:** sequential in Phase 2; add **dependency-aware parallel execution** (run each DAG level
  concurrently, capped by a concurrency limit + `--max-modules`) as a later optimization once the DAG
  and re-decomposition semantics are settled. Not now (YAGNI).

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

### Phase 3 — Course assembly (the stitch) — ✅ IMPLEMENTED (2026-07-20)

Implemented as `forged/curriculum/assembler.py::assemble_course` (+ `_render_course_index`,
`_render_course_report`, both directly testable). `ModuleSpec.remediation_for` (additive, default
`()`) records which capabilities a reactively-added module (Phase 4) was spawned to cover;
`reactive.py` sets it when it builds a remediation module. CLI wiring: `_cmd_course` and
`_build_confirmed` both end by calling the shared `_finalize_course(result, course_dir, fidelity)`,
which calls `assemble_course(...)` then the existing `_report_course_result(...)` — the prior
duplicated tail between the two call sites is gone. Validated by
`tests/test_curriculum_assembler.py` (12 tests: index ordering/prerequisite chain, reactive
provenance line, terminal_ok vs. failed marks, dropped-capability surfacing, notebook-link
presence/absence, plan-fidelity verdict gating, NAV.md prev/next/up + prerequisite links, a module
absent from `CourseResult.modules` is marked "not run" rather than omitted, NAV writing is
best-effort — a module directory that doesn't exist is skipped, never fabricated) plus one-line
extensions to `test_curriculum_model.py`, `test_curriculum_reactive.py`, and `test_cli_course.py`.
Full suite green; `ruff`/`mypy` clean.

Scoped via a dedicated research pass; concrete plan below (historical — now implemented as
described above). Two real gaps surfaced that the
original one-paragraph sketch missed:

- **Provenance gap:** a reactively-added module (Phase 4) records *that* it was added
  (`CourseSpec.rationale` gets an aggregate note), but not *which capability* it covers — no
  per-module attribution survives. Fixed by one additive field (below).
- **Filename collision:** each module dir's `README.md` is already the learner-package README
  (`write_learner_package` → `packaging.write_package`). Per-module cross-links cannot reuse that
  file without coupling Phase 3 to a writer it doesn't own.

**Data-model addition** (`forged/curriculum/model.py`, additive + frozen, defaulted so existing
callers are unaffected):
```python
@dataclass(frozen=True)
class ModuleSpec:
    spec: TopicSpecification
    order: int
    module_prerequisites: tuple[str, ...] = ()
    remediation_for: tuple[str, ...] = ()   # capabilities this module was spawned to cover;
                                            # () ⇒ a proactively-planned module
```
Set once, in `forged/curriculum/reactive.py` where it builds a remediation `ModuleSpec`
(`ModuleSpec(spec=spec, order=…, module_prerequisites=prerequisites, remediation_for=dropped)`).
Coarse-grained by design: `dropped` is the whole round's overflow union, not per-module-attributed
capability sets — an honest "covers: …" line, not false precision.

**New `forged/curriculum/assembler.py`** (mirrors the `deliverables.py` writer convention — a
side-effecting `assemble_*` plus pure, directly-testable `_render_*` string builders):
```python
def assemble_course(
    result: CourseResult, course_dir: Path, *, fidelity: TopicFidelityReport | None = None,
) -> None: ...
def _render_course_index(result: CourseResult) -> str: ...
def _render_course_report(result: CourseResult, fidelity: TopicFidelityReport | None) -> str: ...
```
- Reads `result.course` (the **grown** spec post-Phase-4, never the pre-run input) — every
  reactively-added module must appear.
- Writes course-root `README.md` (ordered index: one line + prerequisite chain + link per
  module; reactively-added modules flagged inline) and **overwrites** course-root `COURSE.md`
  (the pre-run `_persist_course` preview becomes the post-run outcome report: per-module
  terminal_ok/notebook link/dropped-capability rollup, reusing the exact drop-surfacing shape
  `_report_course_result` and `write_agentic_summary`'s Topic Fidelity section already use).
- Per-module cross-links go in a **new `NAV.md`** per module dir (prev/next/up + prerequisite
  links) — not the learner-package `README.md`, to avoid the collision above and keep the
  assembler decoupled from a file another writer owns.

**CLI wiring**: both `_cmd_course` and `_build_confirmed` (`forged/cli.py`) currently end with
`result = _orchestrate_course(...); return _report_course_result(result, course_dir)` —
duplicated identically. Dedupe into one `_finalize_course(result, course_dir, fidelity)` helper
that calls `assemble_course(...)` then `_report_course_result(...)`; swap both call sites to it.
The single-lesson branch in `_cmd_learn` is untouched (no course to assemble).

**Tests** (`tests/test_curriculum_assembler.py`, all unit-level against synthetic `CourseResult`
fixtures, no LLM/network/pipeline): index ordering + prerequisite chain rendering; terminal_ok
vs. failed status marks; dropped-capability surfacing; notebook-link presence/absence; reactive
provenance line renders only when `remediation_for` is non-empty; plan-fidelity verdict line
gated on the optional `fidelity` arg; `assemble_course` writes/overwrites the right files in
`tmp_path`; per-module `NAV.md` prev/next/up correctness; assembler reads the *grown*
`result.course`, not the original plan. Plus one-line extensions to
`test_curriculum_model.py` (new field defaults `()`, frozen), `test_curriculum_reactive.py`
(remediation module records provenance), and `test_cli_course.py` (post-run `README.md`/
`COURSE.md` exist and reflect outcomes).

Files touched: new `forged/curriculum/assembler.py` + `tests/test_curriculum_assembler.py`;
edited `forged/curriculum/model.py`, `forged/curriculum/reactive.py`, `forged/cli.py`, and the
three test files named above.

### Phase 4 — Reactive safety net (the R1 → planner → R1 feedback loop) — ✅ IMPLEMENTED (2026-07-12)
Implemented as `forged/curriculum/reactive.py::run_course_reactive`, opt-in behind
`forged course --redecompose` / `forged learn --redecompose` (both also take `--max-depth`, default 1).
It runs the course via the unchanged `run_course`, then handles overflow; the orchestrator's per-module
hand-down step was extracted to `run_module_with_handdown` so both the sequential loop and the reactive
one seed context identically. The remediation planner is injected as a callback (`RemediationPlanner`),
so `reactive.py` stays LLM-free and unit-testable; the CLI wires the real `CurriculumPlanner` in via
`_make_remediation_planner`. Validated by `tests/test_curriculum_reactive.py` +
`tests/test_cli_course.py::test_redecompose_routes_to_reactive_loop_and_threads_max_depth`.

This is the loop that makes the whole design self-correcting (Kevin's framing): **if a module run is
still too dense, R1 hands the overflow back to the curriculum planner, which plans a new module topic
and feeds it to a fresh R1 run.** Concretely:
- After each module run, read `ModuleResult.topic_fidelity`. **The trigger is the R1 fidelity signal:**
  `missing` non-empty ⇒ the module run *dropped* a requested capability ⇒ the module was over-large for
  one notebook (exactly the R1 symptom, now at module scope).
- Hand the dropped capability(ies) back to the `CurriculumPlanner` as the brief for a **new module**,
  insert it into the course after its prerequisites, and run it through a fresh `run_pipeline`. The
  course grows by exactly the overflow — nothing is lost.
- **Bounded:** re-decomposition is capped by `--max-modules` and a max-depth so the loop always
  terminates; off by default (opt-in), and every re-split is recorded in `COURSE.md`.
- **Trigger nuance:** the *implementable* trigger today is the deterministic fidelity drop. A softer
  "too dense but nothing dropped" signal (low `learner_fit` / high gap-count from the student critic)
  is a *possible future* second trigger — noted, not built (YAGNI) until the drop-based loop proves it
  needs help.
- Tests: a module that drops a capability hands that capability back and yields a new module; bounded
  re-decomposition terminates; the overflow capability ends up covered by the grown course.

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
