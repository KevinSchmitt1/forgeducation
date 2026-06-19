# 11 — Topic Fidelity (R1) — lesson-level

**Status:** ✅ IMPLEMENTED (2026-06-19). This is Half A of a deliberate two-way split. Half B
(the curriculum planner) is **out of scope here**; see `TODO.md` → "Phase 2" and the "Scope
boundary" note below. The only thing the two halves share is the **topic-fidelity signal
contract** defined in Part IV. Validation: full suite green (410), new modules at 100% coverage;
the validating tests are named in Part V.

**Scope adjustment during implementation.** The Phase-2 `topic_infeasible` *graph-termination
mechanism* was descoped to a follow-up: the planner persona now **declares** infeasibility
explicitly in its plan output (an honest, visible `## Topic infeasible` section), and the
deterministic fidelity signal (Phase 3) makes any actual drop visible in `SUMMARY.md`. Wiring a
dedicated terminal state would duplicate that visibility without adding a guarantee, so it was
left out under YAGNI. The honesty acceptance criteria below are met by the persona declaration +
the recorded/surfaced signal. Re-add the terminal state only if a concrete need appears.

**Supersedes the fix direction sketched in** `docs/architecture/10-output-quality-remediation.md`
→ **Part IX / R1**. That doc states the symptom, root cause, and acceptance; this doc is the
implementation plan.

---

## Hand-off — read this first

### Where we are
The agentic loop can **silently drop a capability the `--topic` explicitly requested**. On topic
*"setup **and train** local LLMs on Apple Silicon M1"* the loop produced a well-explained notebook
that executed cleanly (`ok=True`, score 77) but, across iterations v0 → v2, **deleted LoRA
fine-tuning entirely** and rescoped to device-placement fundamentals. The output is *well-explained
but no longer covers "train / fine-tune"* — it does not fulfil the request. This is a correctness
defect, not a polish item.

### Root cause (confirmed in code)
A single critic finding — *"Trainer is used without explicit device configuration; MPS selection
isn't explained"* — was tagged `[BLOCKER / plan]`. That is really a **content/explanation gap**, but
because it was scoped `plan` with BLOCKER severity it hits the classifier's Priority-1 rule:

> `failure.py` → `classify()` Priority 1: a `BLOCKER` in `plan`/`structure` scope →
> `BLOCKER_STRUCTURE` → `router.py` routes to the **planner** ([failure.py:200-215](../../forged/pipeline/failure.py#L200-L215)).

The planner then cleared the blocker the cheapest way a replan can — by **descoping** (removing the
fragile section) rather than scaffolding it. So a finding's **scope tag** decides *scaffold vs.
amputate*:

- `content` → `content_reviser` **adds the missing explanation** (keeps the section).
- `plan` / `structure` → planner **rethinks the lesson** (may delete the section).

**The classifier is correct given correct scope tags.** The defect is upstream: the critic
mis-scoped a content gap as `plan`. Therefore the primary fix is **persona-level**, with a
deterministic backstop so honesty does not depend on the LLM scoping perfectly.

### Division of labour (do not fold R1 into Phase 2)
- **Lesson level (this doc): detect & be honest.** Never *silently* drop a requested capability.
- **Curriculum level (Phase 2): resolve by decomposing.** Once descoping is *visible*, the
  curriculum planner can split an over-large topic into modules so the cut content becomes its own
  lesson. R1's signal is the trigger for that decomposition.

Keeping them separate prevents the silent-drop defect from being multiplied across every module the
planner spawns. The only coupling is the signal contract (Part IV).

---

## Part I — Design decisions

1. **Deterministic detector owns the reusable signal; personas are the backstop.**
   The topic-fidelity signal (Part IV) is produced by a **deterministic** check (cheap, auditable,
   no LLM, honors "no new LLM calls in the classifier core"). Persona-level critic flagging (Part
   III, Phase 1) is added as defense-in-depth for what term-coverage misses. `10-…` Part IX framed
   fidelity as a critic job; we do **both**, with the deterministic detector owning the contract
   Phase 2 consumes.

2. **The deterministic classifier stays unchanged.** `classify()` / `router.py` logic is correct
   given correct scope tags. R1 changes personas, the planner brief-anchoring, and adds a detector +
   signal — not the routing cascade.

3. **The detector is a backstop to flip silent → visible, not a perfect judge.** A narrow
   term-coverage heuristic (like `structure.py`'s anti-hollow check) will miss some cases. That is
   acceptable: paired with persona flagging, even a fragile detector turns a *silent* drop into a
   *recorded, surfaced* one — which is the honesty goal.

4. **Honest termination over silent substitution.** When a topic genuinely cannot be taught for the
   profile, the loop terminates with an explicit reason (e.g. `topic_infeasible`) rather than quietly
   shipping a different, easier lesson.

---

## Part II — Patterns to mirror

| Concern | Source | Pattern |
|---|---|---|
| Deterministic check | [structure.py](../../forged/pipeline/structure.py) | nbformat + stdlib only, no LLM, frozen `*Report`, narrow regex to avoid false positives |
| Signal on state | [state.py `Degradation`](../../forged/pipeline/state.py#L135-L153) + [`with_degradation`](../../forged/pipeline/state.py#L221-L228) | frozen dataclass + `with_*` builder, list-append immutability |
| Check wiring | [reviser.py `_assess_structure`](../../forged/pipeline/agents/reviser.py#L71-L104) | reviser reads artifacts, runs the check, feeds `classify()` / records signal, surfaces in brief |
| Scope vocabulary | [personas/student.md:102-105](../../personas/student.md#L102-L105), [personas/reviewer.md:66-73](../../personas/reviewer.md#L66) | `plan`/`structure`/`code`/`content` drives routing |
| Artifact at setup | [cli.py:258-263](../../forged/cli.py#L258-L263) | `brief` + `lesson_context` persisted as artifacts before the graph runs |

---

## Part III — Phased implementation plan

Each phase is TDD (RED → GREEN → refactor) and must leave the suite green. CI gates
(`ruff`, `mypy`, `pytest --cov-fail-under=80`) run before any phase is called done.

### Phase 0 — Persist structured objectives (dependency)
The structured `TopicSpecification` (objectives, title, focus_areas) is currently only **rendered
into `lesson_context` prose** ([cli.py:261-263](../../forged/cli.py#L261-L263)); it is never persisted
as structured data. The deterministic detector needs the capabilities as data, not prose.

- Persist `topic_spec.json` as an artifact at setup in [cli.py:258-263](../../forged/cli.py#L258-L263),
  alongside `brief` / `lesson_context`.
- Test: setup writes `topic_spec.json` with objectives/title/focus_areas.

### Phase 1 — Sharpen the critic scope rubric (persona-only; the primary fix)
- Edit [personas/student.md:102-105](../../personas/student.md#L102-L105) and
  [personas/reviewer.md:66-73](../../personas/reviewer.md#L66): a *missing or weak explanation of an
  otherwise-correct, executing cell* is `content`, never a `plan`/`structure` BLOCKER. Reserve
  `plan`/`structure` BLOCKER for genuine concept-ordering / prerequisite / "no working demo"
  failures — never for "this correct step is under-explained".
- **No classifier code change.** Add a **regression test**: a `content`-scoped finding on a
  green-executing notebook classifies `CONTENT_QUALITY` → routes to `CONTENT_REVISER`, never
  `BLOCKER_STRUCTURE` / `PLANNER`.

### Phase 2 — Anchor the planner to the brief on replan
The planner already reads `brief` + `revision_brief` ([planner.py:79-84](../../forged/pipeline/agents/planner.py#L79)).
The gap is instruction, not plumbing.

- Strengthen [personas/planner.md](../../personas/planner.md): on replan, the planner may rescope
  *how* a capability is taught but must keep **every** deliverable named in `--topic` / objectives.
  If the topic genuinely cannot fit the profile, it must signal "cannot fit" honestly rather than
  substitute a different, easier lesson.
- Add an honest-termination path (terminal reason `topic_infeasible`) for the genuine-can't-fit case.
- Test: replan prompt assembly includes the brief + the keep-all-capabilities instruction.

### Phase 3 — Deterministic topic-fidelity detector + signal (the Half B seam)
- New `forged/pipeline/fidelity.py`, modeled on `structure.py`:
  `assess_topic_fidelity(executed_nb, objectives) → TopicFidelityReport`. An objective is
  *uncovered* when none of its salient terms appear anywhere in the executed notebook (code +
  markdown + outputs). Narrow matching to avoid false positives.
- Add `TopicFidelitySignal` (Part IV) + `with_topic_fidelity(...)` builder to
  [state.py](../../forged/pipeline/state.py), mirroring `Degradation` / `with_degradation`.
- Wire into [reviser.py](../../forged/pipeline/agents/reviser.py) next to `_assess_structure`: record
  the signal, and surface any `missing` capability in `revision_brief_v{N}` + SUMMARY so a descope is
  **reported, never hidden**.
- Tests: `fidelity.py` unit tests (covered, partially-covered, dropped-capability); signal builder
  immutability; reviser records the signal and surfaces missing capabilities.

### Phase 4 — Docs & close-out
- Update this doc's status to IMPLEMENTED with the validating test names.
- Sync `TODO.md` (R1 → in progress/done; Phase 2 still gated; note the signal contract).
- Run all three CI gates; address reviewer-on-diff findings.

---

## Part IV — The topic-fidelity signal contract (only coupling to Half B)

A frozen value object recorded on `PipelineState` (like `Degradation`). **Stable and additive-only** —
Phase 2 (curriculum planner) consumes `missing` to decide module decomposition.

```python
@dataclass(frozen=True)
class TopicFidelitySignal:
    """Whether the shipped notebook still covers every capability the topic named.

    `missing` non-empty ⇒ a requested capability was dropped. Phase 2 reads it to
    decide whether to decompose the topic into modules. `source` records who produced
    the verdict so a deterministic backstop and a critic flag can coexist.
    """
    requested_capabilities: tuple[str, ...]   # from TopicSpecification objectives/title/focus_areas
    covered: tuple[str, ...]
    missing: tuple[str, ...]
    source: str                               # "deterministic" | "critic"
```

`PipelineState.with_topic_fidelity(signal) -> PipelineState` appends to a `topic_fidelity` tuple via
`replace()`, identical in shape to `with_degradation`.

---

## Part V — Acceptance (mirrors `10-…` Part IX / R1)

- [x] An under-explained but correct, executing step is classified `content` (→ `CONTENT_REVISER`),
      not `blocker_structure`. — personas/student.md + reviewer.md scope rule;
      `test_failure.py::test_r1_under_explained_executing_step_routes_to_content_not_replan`.
- [x] A replan keeps every capability named in `--topic` (the lesson still teaches fine-tuning), or
      reports infeasibility honestly instead of dropping it. — planner.md "Topic fidelity" rule;
      `test_agents_concrete.py::test_planner_replan_message_carries_brief_and_prior_feedback`.
      (Graph-level `topic_infeasible` terminal descoped — see status note.)
- [x] Regression test: a clean-executing notebook whose only weakness is content-scoped routes to
      `CONTENT_REVISER`, never `PLANNER`. — same `test_r1_…` test.
- [x] When a requested capability is dropped, a `TopicFidelitySignal` with non-empty `missing` is
      recorded on the state and surfaced in the run summary — the drop is never silent. —
      `test_agents_concrete.py::test_revisor_records_topic_fidelity_signal_when_capability_dropped`,
      `test_cli_agentic.py::test_agentic_summary_surfaces_dropped_topic_capability`.
- [x] CI gates green (`ruff`, `mypy`, coverage ≥ 80%); `fidelity.py` + `context.py` at 100%.

---

## Part VI — Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Term-coverage heuristic false positives/negatives | MEDIUM | Narrow matching like `structure.py`; treat as a backstop, paired with persona flagging |
| Persona edits don't reliably change LLM scope tagging | MEDIUM | Regression test on the classifier + the deterministic fidelity signal catch what personas miss |
| Coverage dips below 80% from new modules | LOW | TDD per phase |
| `topic_infeasible` termination misfires on a fittable topic | LOW | Persona reserves it for genuine impossibility; covered by tests |

---

## Scope boundary (R1 vs. the curriculum planner)

Lesson level = **detect & be honest** (this doc). Curriculum level = **resolve by decomposing**
(Phase 2). Do **not** fold R1 into Phase 2: fix lesson-level detection/honesty first (it's the
foundation), and treat `TopicFidelitySignal` as the reusable contract Phase 2 *consumes*. The only
coupling is that signal.

---

## References
- `docs/architecture/10-output-quality-remediation.md` → Part IX / R1 — symptom, root cause, acceptance
- `docs/architecture/07-agentic-pipeline-status.md` — current pipeline + known limitations
- `forged/pipeline/failure.py` — the deterministic classifier (Priority-1 is the root-cause site)
- `forged/pipeline/structure.py` — the anti-hollow backstop the detector is modeled on
- `TODO.md` — roadmap; Phase 2 (curriculum planner) is Half B
