# TODO — forgeducation Roadmap

> **▶ Resuming work?** This file is the cold-start brief — current status, what's shipped, what's
> in flight, what's next. See [`CLAUDE.md`](CLAUDE.md) for repo conventions and architecture
> orientation (durable, not state); doc ownership is defined there under "Documentation".

---

## ⛔ BLOCKED — the OpenAI account is out of credits (2026-08-08)

`learn` fails at the CurriculumPlanner with `429 insufficient_quota / credit_balance_exhausted`.
**Nothing paid can run until credits are added.** Everything below that says "needs a run" is
waiting on exactly this.

Part of that balance was spent accidentally: on 2026-08-08 two test-suite invocations made **real,
unconsented agentic runs** (243s and 634s) after a course test was retargeted from `course` to
`learn` — a 1-module fixture routes to the single-lesson branch, which builds real `LLMClient`s. The
exact cost is unrecoverable (pytest rotated the tmp dirs holding `usage.json`). A local guard is in
place; the repo-wide fix is under "Known loose ends".

## 🎯 STATE RIGHT NOW — one change on master, one still open

| Change | Where | Status |
|---|---|---|
| **Provisioning preflight** (#33) | ✅ on `master` (`c3e2613`) | 3 gates green, exercised, **not validated by a run** |
| **One CLI front door + linear engine deleted** (was #34) | ⚠️ **not on master** — `refactor/single-cli-front-door` | 3 gates green, exercised, **not validated by a run** |

**What went wrong with #34, so it isn't repeated:** it was opened as a *stacked* PR with base
`feat/provisioning-preflight` rather than `master`. Merging it therefore merged it into that feature
branch, not into `master`; `master` was updated separately by #33, and the consolidation was left
behind. GitHub reported #34 as MERGED, which it was — into the wrong place. The branch has since
been rebased onto `master` and needs a **fresh PR targeting `master`**.

> **Lesson:** don't open stacked PRs here. Either hold both changes on one branch, or wait for the
> first to land on `master` and rebase the second onto it. A "MERGED" badge is not proof the code
> reached `master` — check `git ls-tree origin/master`.

Also worth knowing: PR #32 was squash-merged, which left a duplicate commit on the feature branches
and made GitHub report a phantom conflict. Rebase onto `origin/master`; don't re-merge.

**Do not merge the remaining change as soon as CI is green** (`CLAUDE.md` norm 3). Add credits, do
the single doc-18 validation run below, then merge.

## 🎯 THEN — RE-RUN THE DOC-18 VALIDATION (criteria 3–5 still unmeasured)

The lesson-mode debias **works** and is proven across two runs. What is *not* yet known is whether
the resulting notebooks are actually better, because **no module has produced a notebook yet** — the
attempts died in environment provisioning, not in the pipeline. The allow-list blocker is fixed
(PR #31) and provisioning now fails *before* the expensive stage (PR #33). Run it again.

```bash
.venv/bin/python -m forged.cli learn \
  --topic "Teach me how to work with AI agents: how to build them, build harnesses for them, and optimize agentic workflows. At the same time, teach me how to optimize my own workflow with AI and make my AI setup learn together with me — meaning how I manage all the files and data on my machine, and how the architecture of that should look." \
  --learner-profile templates/examples/kevin_learner.yaml
```

Use `learn` (the same front door as the 2026-07-28 baseline, so it is like-for-like). The plan gate
shows each module's mode **before** any spend, warns when every module shares one mode, and takes
`make module 2 conceptual` as a deterministic override that costs no re-plan.

### Criteria — where they stand

| # | Criterion | Status |
|---|---|---|
| 1 | Planner emits a **mix** of modes (not all `executable`) | ✅ **PASS**, three times |
| 2 | Gate shows modes; a mode can be overridden without re-planning | ✅ works |
| 3 | Subject stays concrete instead of drifting to computable proxies | ⬜ **unmeasured** — no notebook yet |
| 4 | Code share drops from the 76–89% band | ⬜ **unmeasured** — needs a built mixed course |
| 5 | All modules provision | ⬜ blocked twice by the allow-list; should now pass |

**Plan gate observed 2026-08-08** (planned only, not built — this is where the credits ran out).
4 modules: `[0] Personal AI Workspace & Architecture · artifact`, `[1] Building a Modular AI Agent ·
executable`, `[2] Agent Harnesses: Testing, Evaluation, CI · executable`, `[3] Optimizing Agentic
Workflows & Co-Learning Pipelines · executable`. Est. ~$0.80–$2.00 / ~40–48 min. Fidelity: `ⓘ not
assessed` (no `--topic-spec`, so no discrete capabilities to check — correct behaviour, PR #30).

Two judgement calls for whoever runs it next:
- **Module 3 is the widest** — RAG pipeline *and* drift monitoring *and* retrain-vs-prompt-tune
  policy *and* rollback. Most likely to reproduce the original "code-heavy, not practical"
  complaint. Candidate for `make module 3 artifact` or a split at the gate.
- **Passing `--topic-spec` would turn the fidelity check on.** As run, nothing verifies the 4
  modules cover what the topic asked for.

> **Read the notebooks, not just the gate.** Criterion 1 is settled. The open question is Kevin's
> original complaint: does an `artifact` lesson on personal workflow architecture hand him a scaffold
> he would keep, and does it stay concrete about Claude Code rather than drifting to generic tooling?
> Criterion 1 passing while 3 fails would prove fidelity drift is an **independent** defect and
> re-open it as its own doc.

### The runs so far

| Run | Modes | Outcome |
|---|---|---|
| `20260728-145848_course_…` | 4 × `executable` | the finding that produced doc 18 |
| `20260730-215250_course_…` | `executable` + **`artifact`** | debias confirmed; module 1 crashed, and destroyed its own evidence → PR #29 |
| `20260730-224009_course_…` | mixed again, light deps | **0/2** — both modules refused by the package allow-list → PR #31 removed it |

Full diagnosis, decisions, and corrections:
[`docs/architecture/18-mode-selection-bias-and-run-honesty.md`](docs/architecture/18-mode-selection-bias-and-run-honesty.md).

### ✅ DONE (2026-08-08) — provisioning is validated BEFORE the expensive stage

The graph ran `planner → code_author → executor` with provisioning inside the **executor**, so the
expensive gpt-5 `code_author` pass produced a notebook and *then* provisioning could refuse —
throwing the paid work away. That is exactly what both 2026-07-30 runs did.

Shipped: a `provision_gate` node between `planner` and `code_author`, present only when provisioning
is enabled (`forged/pipeline/provision_gate.py`). The attempt itself was extracted from
`ExecutorAgent._provision_kernel` and is now shared by both callers, so failure behaviour is
byte-identical — same `provision_failed` degradation, same honest `execution_report`, same terminal
state — only *earlier*. The executor still calls it, because the `content_reviser → executor` edge
re-enters execution without passing the planner; for unchanged requirements that call is a
content-addressed cache hit (a marker-file check), so the happy path costs nothing extra.

**This is a timing change, not a policy one.** The gate applies no allow-list and refuses no package
(see `DEFAULT_ALLOWED_PACKAGES` — opt-in only since PR #31). It only moves *when* we discover pip
cannot build what the plan asked for.

Status: **test-green and exercised at the CLI entry point; not yet validated by a paid run.** The
next real `learn` run is what proves it — a provisioning failure should now appear before any
notebook exists.

### ✅ DONE (2026-08-08) — one CLI front door; the linear engine deleted

`build`, `agentic` and `course` are gone. `forged learn` is the only build command: it plans first
and the CurriculumPlanner decides lesson-vs-course, which is what the CLAUDE.md note at the top of
this repo asked for. Choosing a command meant pre-committing to a shape before anything had sized
the topic — and getting that wrong is the origin of the over-large-lesson complaint.

- `--plan-only` / `--out` moved from `course` onto `learn`, so the zero-cost "show me the plan"
  path survives. `pipelines` and `clean` remain as utilities.
- The **linear engine is deleted**: `orchestrator.py`, `agent.py`, `gate.py`, `report.py` and
  `ledger.py` were reachable only from `build`. ~2,900 lines gone with `tests/test_pipeline.py`.
  (`ledger.py` parsed the critics' old free-text `[SEVERITY] cell N — issue` format; the agentic
  path has used JSON-schema grader output since doc 15, so nothing else referenced it.)
  `notebook.py` stays — it is shared with the agentic agents.
- **Coverage-preserving detail:** `tests/test_progress.py` recovers the two Spinner tests that
  lived in the deleted `test_pipeline.py`. `forged/progress.py` survives (the CLI uses it) and had
  fallen to 37% before they were restored.
- Tests were retargeted, not dropped: `test_cli_agentic.py` → `test_single_lesson.py` (drives
  `_run_agentic_lesson`, the surviving single-lesson lifecycle); `test_cli_course.py` →
  `test_cli_course_path.py` (drives `learn` with a stubbed multi-module planner — the real way the
  course path is now reached).
- **Still to check on the next run:** nothing about the engines changed, but `learn` is now the only
  path in, so any run exercises it by definition.

### Known loose ends (neither blocking)

- **CI smoke test for the entry point (started, not finished).** A `tests/test_entrypoint_smoke.py`
  was drafted this session and deliberately **not committed** — 2 of its 7 tests were still failing
  and half-working tests are worse than none. What it should assert, via `subprocess` on
  `python -m forged.cli`: each command starts and rejects an empty `--topic` with exit 2 and no
  traceback; `--help` and `pipelines` exit 0. All free, no network. This is the mechanical guard for
  `CLAUDE.md` norm 1 — the class of bug that put a `NameError` on `master` past 700 green tests.
  Now smaller than when it was drafted: there are three commands to cover (`learn`, `pipelines`,
  `clean`), not six.
- **Nothing repo-wide stops a test from making a live paid call.** On 2026-08-08, retargeting a
  course test from `course` to `learn` silently turned a plan-only assertion into two **real, paid
  agentic runs** (243s and 634s, full planner→…→reviser with revision iterations) — because a
  1-module plan routes to the single-lesson branch, which constructs real `LLMClient`s. It failed on
  the assertion *after* spending. The same class of bug hit the doc-14 wiring pass. A local autouse
  guard now covers `tests/test_cli_course_path.py`, but that is a per-file fix for a repo-wide hole.
  **Suggested mechanical guard:** an autouse `conftest.py` fixture that raises if `LLMClient` (or
  `ExecutorStage`) is constructed, with an explicit opt-in marker (e.g. `@pytest.mark.live`) for the
  handful of tests that genuinely want a real run. Cost of not doing it is measured in paid runs.
- **`setup_logging` accumulates handlers.** It adds a console + file handler on every call without
  clearing existing ones. The course orchestrator now calls it once per module (doc 18 crash
  diagnostics), so every earlier module's file handler stays attached and keeps receiving later
  modules' records — visible in `runs/20260730-224009_…/module_0_…/pipeline.log`, which contains
  module 1's provisioning failure. Fix: clear prior handlers (or attach a per-run handler and
  detach it) before adding.

- **CI never invokes the CLI the way a user does.** Tests `import forged.cli`; users run
  `python -m forged.cli`. A NameError shipped to `master` through 700 green tests, ruff and mypy
  because of exactly this (#30). A smoke test asserting `learn --topic "   "` exits with the usage
  error would close it — no network, no spend. A structural test now guards the specific
  "defined after the `__main__` guard" mistake, but not the general hole.
  **Update 2026-08-08:** the blocker noted above is gone. `agentic`'s divergent exit code was the
  open question, and that command no longer exists — the CLI is one front door, so the test only has
  to assert `learn --topic "   "` exits 2 (verified by hand at the `-m` entry point, not automated).
- **`personas/code_author.md:22`** still calls `conceptual` "(rare)" — a leftover anchor stripped
  from `planner.md`, `reviewer.md` and `student.md` when the mode selection was debiased.

### Also still open — Run A (regression re-run)

Same input as the original "local LLMs" runs, to check the program improved.

```bash
.venv/bin/python -m forged.cli learn \
  --topic "How to setup and train local LLM's on apple silicon m1" \
  --learner-profile templates/examples/kevin_learner.yaml \
  --config config/pipeline.review-loop.yaml
```

> Was a `forged agentic --run-dir …` invocation before the CLI was collapsed to one front door
> (2026-08-08). `learn` will size this topic itself; force the single-lesson shape at the plan gate
> ("just make it one notebook") if you want a like-for-like comparison with the old run.

- **Topic (raw `--topic`):** `How to setup and train local LLM's on apple silicon m1`
- **Learner profile:** `templates/examples/kevin_learner.yaml` (Kevin: Junior Data Scientist)
- **Topic-spec:** none — defaults used.
- **Baseline to beat** (old `runs/localLLM-r1-validate`): "Acceptable" but had
  **student grade-parse failures (×2), a reviewer empty-content failure, and a topic-fidelity
  DROP** (silently dropped the "train" capability).
- **"Did it improve" checks:** fewer/zero degradations, **no fidelity drop**, plus qualitative
  notebook quality.

> **Lesson modes shipped (2026-07-28, PR #25, merged to `master`)**, and were **observed failing
> to fire** on the very next paid run — see the doc-18 section at the top of this file. The
> machinery and its critics are fine; the planner's mode-selection text was the defect. Designs:
> `docs/architecture/17-lesson-modes.md` (the modes),
> `docs/architecture/18-mode-selection-bias-and-run-honesty.md` (why they never fired).

---

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

- **Lesson modes** (PR #25) — planner-inferred `executable` / `artifact` / `conceptual`
  - non-compute topics (agent building, personas, scaffolding) are teachable: `artifact` cells
    build-and-validate deliverables instead of computing; the anti-hollow gate + classifier are
    mode-aware; SUMMARY reports the mode + which verification ran
  - purely inferred (no user flag/state field); executable path byte-for-byte unchanged
  - **needs live-run validation** (Run B above) — logic is test-green only
  - see `docs/architecture/17-lesson-modes.md`

### ✅ Recently Completed

- **Lesson-mode debias + run honesty (doc 18) — PRs #28, #29, #30, #31 (2026-07-30).** The
  2026-07-28 course run declared `executable` for all four modules, and everything Kevin complained
  about (code-heavy, not practical, broken modules) traced to that one biased persona section. The
  mode machinery from doc 17 and its critics were checked and found *fine* — no new agents were
  needed. Shipped: planner/curriculum-planner personas debiased around "what does the learner have
  at the end?" plus a substitution test; per-module `lesson_mode` on `ModuleSpec`, shown at the plan
  gate with a deterministic `set_mode` override and a homogeneous-mode warning; `course` wired to the
  gate (now needs `--yes` on a non-TTY); the `pip install` prose miner deleted and the unfenced
  `requirements` heading parsed; crash diagnostics (`FAILED.md` + per-module `pipeline.log`) so a
  module that raises can no longer destroy its own evidence; the false `⚠ DROPPED` fidelity line
  replaced by a third outcome, `ⓘ not assessed`; and the package allow-list removed as a default.
  **Confirmed on two live runs: the planner now emits a mix of modes.** See
  `docs/architecture/18-mode-selection-bias-and-run-honesty.md` for the full causal chain, the
  rejected alternatives, and two corrections to its own earlier evidence.

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

**Still owed for this feature:** the deliverable-writer extraction is **done** (writers now live in
`forged/deliverables.py`; see below). Remaining: a **paid live `forged learn` smoke run** (1-module
topic → single-lesson path; then a small course).

---

### ✅ DONE (2026-07-20): Curriculum planner Phase 3 — course assembly

Implemented on `feat/curriculum-course-assembly`. See `docs/architecture/13-curriculum-planner.md`
Phase 3. Stitches per-module outputs into one course: index `README.md` (ordered modules,
prerequisite cross-links, reactively-added modules flagged) + aggregate `COURSE.md` (post-run
outcomes/degradations, overwriting the pre-run `_persist_course` preview) + a per-module `NAV.md`
(prev/next/up + prerequisite links, kept separate from the learner-package `README.md` it doesn't
own). New `forged/curriculum/assembler.py`; additive `ModuleSpec.remediation_for` field records a
reactively-added module's provenance; `_cmd_course`/`_build_confirmed` deduped into one
`_finalize_course` helper. Phase 4 (reactive safety net) was already ✅ DONE (2026-07-12).
**Phase 5 (CLI surface + docs close-out) is also ✅ DONE (2026-07-20)** — the CLI surface was
already complete (built incrementally across Phases 1–4); this close-out flipped doc 13's status
to fully IMPLEMENTED and confirmed all three CI gates green (576 passed, 92.80% coverage) plus a
clean reviewer-on-diff pass on the Phase 3 diff (0 CRITICAL/HIGH, 2 LOW cosmetic notes not
requiring a fix). **The curriculum planner (doc 13) is now fully implemented, all 5 phases.**

### ✅ DONE (2026-07-20): Doc 14 Part III — escalation workflow

Implemented on `feat/readiness-escalation-workflow`. See
`docs/architecture/14-code-explanation-and-readiness.md` Part III. A pre-flight
`ReadinessAssessor` inside `forged learn` catches a topic the `CurriculumPlanner` sized to 1
module but that's too hard for *this* learner's profile, before any gpt-5 spend on an unwanted
beachhead (Phase 4's reactive net already catches the same overflow, but only *after* a wasted
build). New: `forged/curriculum/readiness.py`, `personas/readiness_assessor.md`, a new
`ReadinessVerdict` dataclass in `forged/curriculum/model.py` (deliberately not an extension of
`TopicFidelitySignal`). `forged agentic` is untouched — the escalation lives in `forged learn`
only, reusing the existing confirmation gate unchanged. All three CI gates green (583 passed,
92.57% coverage). **Caught mid-implementation:** the first wiring pass made 3 pre-existing
`test_cli_learn.py` tests issue live, unconsented OpenAI calls (an un-mocked 1-module course
constructed a real `ReadinessAssessor`/`LLMClient`) — fixed by mocking `cli.ReadinessAssessor`
in every test that reaches the pre-flight, same as every test already mocks
`cli.CurriculumPlanner`.

- **Cleanup (known gap): DONE** — the per-run deliverable writers now live in `forged/deliverables.py`
  (`write_agentic_summary`/`write_final_notebook`/`write_learner_package`); both the single-lesson CLI
  path and the curriculum orchestrator import them there, so the orchestrator's deferred `forged.cli`
  import is gone.
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

## Curriculum Planner (Half B) — design questions

**Status:** All 5 phases **implemented** (plan + orchestrate + assemble + reactive safety net +
CLI/docs close-out; see Recently Completed and `docs/architecture/13-curriculum-planner.md`). The
decisions below were resolved during build; one deferred-by-design question remains, not blocking
any phase.

**Resolved during Phases 1–2:**

1. **Sequential vs. parallel?** Sequential now; dependency-aware parallel deferred (the modules form a
   DAG, and because only *objectives* are folded into prior knowledge there is no hard data dependency
   forcing strict order — so parallel is feasible later). See doc 13 Part I.b.
2. **Learner profile global or per-module?** Per-module **augmentation** — each later module's profile
   gains earlier modules' objectives as prior knowledge (the context hand-down), so the learner "learns
   consecutively." Base profile never mutated.
3. **Cross-module coverage validation.** Deterministic `assess_course_fidelity` (union-coverage) checks
   the plan covers every requested capability before any run.
4. **Course-level manifest/index contract (Phase 3 assembly).** `assemble_course` writes an ordered
   `README.md` index + a post-run `COURSE.md` outcome report + per-module `NAV.md` cross-links.
5. **Reactive re-decomposition policy + bounds when a module is still over-large (Phase 4).** Bounded
   by `--max-modules` + `max_depth`; every re-split recorded in the grown `CourseSpec.rationale` and
   now also tagged per-module via `ModuleSpec.remediation_for`.

**Deferred by design (YAGNI, not blocking any phase):**

1. When (if ever) to turn on parallel module execution.

---

## Dependencies

- **Doc 14 Part III** (escalation workflow) builds on the merged curriculum planner (all 5 phases
  done; no external gate).
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
- `docs/architecture/13-curriculum-planner.md` — curriculum planner (Half B) — all 5 phases DONE
- `docs/architecture/14-code-explanation-and-readiness.md` — code maps, cell briefs, readiness
  verdict — all parts DONE (2026-07-20), including Part III (escalation workflow)
- `docs/architecture/15-structured-grader-output.md` — structured (JSON-schema) grader outputs — done
- `docs/architecture/16-smart-front-door.md` — `forged learn` interactive plan gate — IMPLEMENTED
- `CLAUDE.md` — agent orientation, conventions, current state + next task, extending the system
- `templates/README.md` — user-facing structured input guide
