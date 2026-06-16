# Output-Quality Remediation — Problem Analysis & Implementation Plan

**As of:** 2026-06-16
**Status:** IN PROGRESS — Phases 1–3 of 6 complete (offline, zero API spend so far). Phases 4–6 remain.
**Source run analysed:** `runs/localLLM/` (topic: *"setup and train local LLMs on Apple Silicon M1"*, learner: Kevin — junior DS→AI). Ended **non-acceptable**, quality score 50, reviser budget exhausted, 4 iterations, 656s.
**Decisions locked:** D1 = provision env **on by default** (per-run venv); D2 = **separate** `ContentReviserAgent`; P2 = **rubric/dimensioned** student scoring.

> Out of scope (already fixed): the `temperature=0.4` rejection on gpt-5-mini, and gpt-5 returning empty content via `finish_reason='length'` (max_tokens raised).

---

## Hand-off — read this first

This section is for the next agent/session picking up the work. The plan below
(Parts I–VIII) is the design of record; this section is the live state.

### Where we are
- **Phase 1 (honest signals + rubric scoring) — ✅ DONE.**
- **Phase 2 (deterministic structural / anti-hollow gate) — ✅ DONE.**
- **Phase 3 (dependency extraction + self-contained deliverable) — ✅ DONE.**
- **Phases 4–6 — ⏳ NOT STARTED.** Next up: **Phase 4 (real agentic prose Reviser +
  dimensioned routing)** — the first control-flow change, and the first **High**-complexity phase.

### Repo state (important)
- **Phases 1–2 are committed** on branch `feat/output-quality-phases-1-2`. **Phase 3 is
  uncommitted** in the working tree on that branch. The user controls git; do not
  commit/push unless asked.
- The branch also carries **pre-existing changes that are NOT part of this project**
  (e.g. a `--brief`→`--topic` CLI rename in `forged/cli.py`, plus edits to `config/`,
  `forged/config.py`, `forged/llm.py`, template files). Don't attribute those to this
  project; don't revert them.
- Verification baseline after Phase 3: **`pytest tests/` → 363 passed; `ruff check
  forged tests` clean; `mypy` clean.** Use `.venv/bin/python -m pytest`, `.venv/bin/ruff`,
  `.venv/bin/mypy`. The full suite takes ~75s (real notebook execution in some tests).
  The two new modules are at **100% line coverage** (matching `structure.py`/`failure.py`).

### What Phase 1 shipped (files + intent)
- `forged/pipeline/state.py` — `Degradation` frozen dataclass + `degradations` list on
  `PipelineState` + `with_degradation()`. Records every silent fallback.
- `forged/pipeline/failure.py` — `RubricScores` (5 dims: structure, explanation_depth,
  code_clarity, correctness, learner_fit; `composite()` = equal-weighted mean).
  `GradeReport` gained `rubric` + `graded` fields. **New classifier branch:** a
  `graded=False` report → `UNCLASSIFIABLE` (priority 3), distinct from `grade_report=None`
  (grader-not-run → still ACCEPTABLE when execution ok). `RUBRIC_DIMENSIONS` is the
  canonical tuple — import it, don't redefine.
- `forged/pipeline/agents/student.py` — on LLM failure/unparseable output writes a
  `graded=False` report + records a `Degradation` (no more neutral-50). Derives
  `quality_score` from the rubric composite (the 5 dims are the source of truth, not a
  separate LLM scalar). Rejects bool/out-of-range rubric values.
- `forged/pipeline/agents/code_author.py` — records a `Degradation` when it falls back to
  stub cells.
- `forged/pipeline/agents/reviser.py` — reads `graded`+`rubric` from the grade JSON;
  revision brief now includes the rubric breakdown + cell-referenced findings.
- `forged/cli.py` — `_write_agentic_summary` adds a **Degradations** section; success path
  warns when degradations occurred.
- `personas/student.md` — output schema now requires the 5-dimension `rubric`.

### What Phase 2 shipped (files + intent)
- `forged/pipeline/structure.py` — NEW. `StructuralReport` (frozen; `reasons` is a tuple)
  + `assess_structure(executed_notebook_json) -> StructuralReport`. Flags `is_hollow` when:
  no code cell produced real output (≥2 code cells, none printed/displayed, none skipped),
  OR ≥50% of code cells were skipped, OR almost no explanatory content. Pure, deterministic,
  nbformat+stdlib only. **Skip detection is deliberately conservative** (only "skipped"/
  "skipping" verb forms, excludes zero-count "skipped: 0", and only counts a cell as skipped
  when its output is short — `SKIP_MAX_OUTPUT_CHARS=200` — so the word can't fire inside a
  large genuine output). This conservatism is intentional: a false positive blocks a *good*
  lesson, which is worse than missing some hollow variants (the student rubric is the first
  line of defense).
- `forged/pipeline/failure.py` — `classify()` gained an optional `structural_report` param.
  At the ACCEPTABLE gate only (priority 6), a hollow notebook → `UNCLASSIFIABLE` with the
  structural reasons. Minimal blast radius — cannot pre-empt CODE_QUALITY/TEST_FAILURE/
  CONTENT_QUALITY/BLOCKER_STRUCTURE.
- `forged/pipeline/router.py` — `UNCLASSIFIABLE` now terminates with the classifier's
  *specific* reason (so structural detail reaches `SUMMARY.md`), not a generic line.
- `forged/pipeline/agents/reviser.py` — `_assess_structure()` reads the executor's
  executed-with-outputs notebook from `store.run_dir` via
  `forged.executor.executed_notebook_filename(...)`, degrades to `None` if absent/unparseable.
- **Cost-conscious design choice:** a hollow notebook **terminates** (cheap) rather than
  looping to replan — replanning can't conjure a missing runtime (that's Phase 5).

### What Phase 3 shipped (files + intent)
- `personas/planner.md` — the `## Prerequisites` section now also requires a fenced
  ` ```requirements ` block: pip-installable packages only, one per line, PEP 508 style.
  Conda/hardware/model-download notes stay in the prose; the block is the machine
  contract. An empty block is allowed (explicitly "no third-party deps").
- `forged/pipeline/dependencies.py` — NEW. `Requirement` + `RequirementSet` (both frozen)
  and `extract_requirements(plan_md) -> RequirementSet`. **Structured block wins** (even
  when empty — an explicit "no deps" is authoritative); else a **prose fallback** scans
  `pip install …` lines; else `source="none"`. `requirements_hash` is a sha256 over the
  **sorted, normalized** requirement lines (order-independent, stable, empty-set has a
  fixed digest) — this is the key **Phase 5's content-addressed venv cache will use**
  (Phase 5 combines it with the interpreter version). `render_txt()` emits pip-parseable
  output. Stdlib only (re/hashlib/dataclasses); no pipeline imports, mirroring `structure.py`.
  **Prose fallback is deliberately conservative:** a `pip install …` phrase whose first
  token is an English function word (`the`, `then`, `packages`, …) is treated as a prose
  decoy and skipped, so a sentence like *"then pip install the HF packages above"* never
  fabricates deps. A missed legacy dep beats a fabricated one — the structured block is
  the trustworthy path. (Verified against the real localLLM plan: clean 6-package extract.)
- `forged/packaging.py` — NEW. `PackageContext` (topic + learner) + `PackageResult` +
  `write_package(run_dir, plan_md, ctx)`. Writes `requirements.txt` (from the extractor)
  and a learner-facing `README.md` (what it teaches ← `## Learning objectives`; who for ←
  learner; setup ← `## Prerequisites` prose with fenced blocks stripped; how to run).
  Pure string templating + two file writes. Returns the `RequirementSet` so callers can
  record the hash without re-parsing. 100% covered.
- `forged/orchestrator.py` (linear) — `README.md`/`requirements.txt` added to
  `RETAINED_FILES` (so the prune keeps them); `_finalize` calls `write_package` from the
  `lesson_plan` artifact before `store.finalize`, and records `requirements_hash` in the
  manifest. Success path only (the crucial-open failure path returns early and keeps all
  debug files anyway).
- `forged/cli.py` (agentic) — after the notebook is written, `_write_learner_package`
  reads the latest `lesson_plan_v{N}` from state and writes the package. **Best-effort**
  (logs and continues on `OSError`) and runs **regardless of terminal_ok**, so even a
  degraded/non-acceptable agentic run still ships a usable README + deps (the agentic run
  dir is never pruned).

### Conventions followed (keep doing these)
- TDD: write/adjust tests first; every change kept the suite green.
- Immutability: only mutate `PipelineState` via `with_*` builders; value objects are
  `@dataclass(frozen=True)` with tuple (not list) collections where practical.
- Each phase ends with `python-reviewer` on the diff (planned review gate) and all
  CRITICAL/HIGH/MEDIUM findings addressed. Reviewers run once per phase, on the diff only
  (cost discipline). The architect pass was deliberately deferred to Phase 4/5 where the
  graph rewire and subprocess/provisioning work actually need it.

### How to resume (Phase 4)
Follow **Part III → Phase 4** below. This is the first **control-flow** change, so the
plan's `architect` review of the graph rewire + budget/loop invariants is warranted before
coding. Core tasks: build `forged/pipeline/agents/content_reviser.py` (LLM agent on
`personas/reviser.md`, mirroring `code_author`'s output/parse/fallback shape and recording
a `Degradation` on fallback), add a `content_reviser` node + `content_reviser → executor`
edge in `forged/pipeline/graph.py`, and route `CONTENT_QUALITY → content_reviser` in
`forged/pipeline/router.py` while preserving the budget/termination invariants (offline
graph tests with a mocked LLM first — assert a *new* notebook version is produced and
re-graded, and that the loop still terminates). Still offline — no API spend through Phase 4.

---

## Part I — Problem Analysis

### The symptom

As the actual target learner, the delivered `lesson.ipynb` is **unusable**: explanations are thin-to-absent, the code is unstructured, and the lesson never demonstrates its own point. This defeats the project's premise (*"teaching material checked against what the code really does"*).

Concrete evidence from the shipped notebook:

- **Every substantive cell skipped.** The execution env has no `torch`/`transformers`, so baseline generation, training, and after-tuning comparison all printed `"... skipped: missing torch/transformers"`. Only a 5-token fallback masking demo ran. The whole lesson (*fine-tune and compare*) never executed.
- **Yet the run reports green.** `execution_report_v3.json` = `{"ok": true, "failed_cells": []}`. Nothing failed because everything was guarded out.
- **Explanations are stubs.** Markdown cells are 1–2 sentences describing what a cell "expects" rather than teaching the concept.

### Root causes (prioritized)

**P0 — "Green execution" ≠ "pedagogically real"; the reality-check passes a hollow notebook.**
The success signal is `execution_report.ok` plus a student score ([failure.py:206-219](../../forged/pipeline/failure.py#L206-L219)). A notebook whose payload is behind `if HAVE_DEPS:` guards and **skips** still reports `ok: true`. The executor cannot tell "demonstrated the concept" from "no-op'd the substance," so nothing is caught. Compounded by topic↔environment mismatch: the lesson *requires* torch/MPS, the executor env *lacks* them, and the code_author's graceful-degrade setup check turns that conflict into a silently empty lesson. Wasted signal: the planner already emits `## Prerequisites` with packages/versions ([personas/planner.md](../../personas/planner.md)), but that list is only inlined into the setup cell — never materialized as a dependency file nor used to provision the env.

**P1 — The agentic Reviser cannot improve prose (persona ↔ implementation mismatch).**
`personas/reviser.md` describes a full notebook-rewriting agent. The agentic `RevisorAgent` ([agents/reviser.py](../../forged/pipeline/agents/reviser.py)) makes **no LLM call** — it is pure deterministic routing. So `CONTENT_QUALITY` (score < 80 → route to reviser, [router.py:108](../../forged/pipeline/router.py#L108)) is a **dead route**: nothing rewrites the prose. Budget is 1 → burns one lap → terminates. This is *the* reason poor explanations never improve in the agentic path.

**P2 — The only content-quality signal is a single fragile student score.**
Content quality reduces to one 0–100 number from one LLM call, with no rubric. When the student call fails it falls back to a **neutral 50** ([student.py:23](../../forged/pipeline/agents/student.py#L23), [student.py:48-50](../../forged/pipeline/agents/student.py#L48-L50)). In this run the final student call returned empty → neutral 50 → `CONTENT_QUALITY` → no-op reviser → terminate. So the final verdict was an **infrastructure failure misclassified as mediocre content**, scored by a value never actually computed.

**P3 — Revision briefs are too thin to steer regeneration.**
On reroute, the brief is generic — "Fix the code failures" / "Revise the lesson structure" ([reviser.py:187-193](../../forged/pipeline/agents/reviser.py#L187-L193)). When the student report is the neutral fallback, `findings` is empty, so the rerouted agent gets no specifics and re-rolls. Iterations wander instead of converging.

**P4 — CodeAuthor's empty-LLM fallback collapses content silently.**
On unparseable/empty output, code_author emits a 2-cell stub and proceeds as if authored, logged only as `WARNING` ([code_author.py:27-38](../../forged/pipeline/agents/code_author.py#L27-L38)). The silent-degradation design is a latent quality cliff.

**P5 — No structural/pedagogical gate distinct from execution.**
Nothing deterministically checks progressive sections, explanation-per-concept, or a worked example that **actually executed** (vs. skipped). "Structure" is only caught if the LLM student emits a correctly-scoped `BLOCKER` ([failure.py:98-107](../../forged/pipeline/failure.py#L98-L107)) — which it didn't (`findings: []`).

**P6 — The deliverable is not self-contained or reproducible.**
The run dir ships `lesson.ipynb` + `SUMMARY.md` (+ internal `manifest.json` on the linear path, [artifacts.py:110-122](../../forged/artifacts.py#L110-L122)) and nothing else actionable: **no dependency manifest** (`requirements.txt`/`pyproject.toml`) and **no learner-facing README**. `SUMMARY.md` is a pipeline status report, not a guide for the learner the lesson is *for*.

---

## Part II — Design decisions

**D1 — Environment provisioning is ON by default.**
Every agentic run derives the lesson's environment from the planner's prerequisites, builds a **per-run isolated venv**, installs the extracted requirements, and executes the notebook against that kernel so cells run for real. Because provisioning is unconditional, a **content-addressed cache** is mandatory: a base venv / wheel cache **keyed by a hash of the resolved requirements** so heavy deps (e.g. torch ~2 GB) are downloaded once and reused across runs. Provisioning is bounded: install timeout, total-size cap, and a package allow-list. If essential deps cannot be installed, the run **fails honestly** (via P0/P5) rather than degrading to a green hollow notebook.

**D2 — Separate `ContentReviserAgent`.**
The deterministic router (`RevisorAgent`) stays as-is and keeps owning routing. A new LLM-backed `ContentReviserAgent` (consuming `personas/reviser.md`) becomes the **target** of the `CONTENT_QUALITY` route, rewrites the whole notebook from student findings, then hands to the executor for re-run and re-grade.

**D3 — Rubric/dimensioned student scoring (P2 expanded).**
The student emits **named dimensions** (e.g. `structure`, `explanation_depth`, `code_clarity`, `correctness`, `learner_fit`), each 0–100, plus a composite. Dimensions feed routing: low `structure` → `BLOCKER_STRUCTURE` (planner); low `code_clarity`/`correctness` → code_author; low `explanation_depth`/`learner_fit` → `ContentReviserAgent`. A **failed** student call is its own signal — never a content score.

---

## Part III — Phased implementation plan

Ordering principle: **make signals honest before spending money to improve them.** Phases 1–4 are developed and tested with **mocked LLMs / tiny deps** (no real API or torch spend). Phase 5 is the first to provision for real.

### Phase 1 — Honest signals + rubric scoring (P2, P3, P4) — ✅ DONE
- **state.py:** add immutable `degradations: tuple[Degradation, ...]` + `with_degradation(...)`.
- **GradeReport ([failure.py](../../forged/pipeline/failure.py)) + [personas/student.md](../../personas/student.md):** dimensioned rubric scores + composite; structured cell-referenced findings always populated.
- **[student.py](../../forged/pipeline/agents/student.py):** separate "LLM call failed" (→ degradation + distinct signal) from "graded low" (→ real composite). No more neutral-50-as-score.
- **[code_author.py:27-38](../../forged/pipeline/agents/code_author.py#L27-L38):** record a degradation when fallback cells are used.
- **[report.py](../../forged/report.py):** surface a **Degradations** section in `SUMMARY.md`; a degraded run cannot silently exit `0`.
- **[reviser.py:187-193](../../forged/pipeline/agents/reviser.py#L187-L193):** thicken briefs with the now-populated cell-referenced findings.
- **Delegate:** `silent-failure-hunter` (audit swallow/fallback sites) → `tdd-guide` (test-first) → `python-reviewer`.
- **Validate:** `pytest -q tests/pipeline/`; failed student call ≠ score 50 and appears in SUMMARY; rubric dimensions present.
- **Complexity:** Medium.

### Phase 2 — Deterministic structural gate + skip detection (P5, half of P0) — ✅ DONE
- **NEW `forged/pipeline/structure.py`:** deterministic checks — min concept sections, markdown-per-code ratio, **"worked example actually executed"** (detect skip-sentinels / empty outputs).
- **[failure.py](../../forged/pipeline/failure.py):** insert a structural signal into the cascade so a hollow notebook → not `ACCEPTABLE` (keep the docstring priority table in sync).
- **Delegate:** `architect` (cascade placement) → `tdd-guide` → `python-reviewer`.
- **Validate:** `pytest --cov=forged.pipeline.structure` (target 100% like `failure.py`); a fixture of the localLLM hollow notebook now classifies non-acceptable.
- **Complexity:** Medium.

### Phase 3 — Dependency extraction + self-contained deliverable (P6, half of P0) — ✅ DONE
- **[personas/planner.md](../../personas/planner.md):** also emit a machine-readable fenced `requirements` block alongside the prose `## Prerequisites`.
- **NEW `forged/pipeline/dependencies.py`:** deterministic extractor (structured block first, regex-on-prose fallback) → normalized dep list + a stable **requirements hash** (consumed by Phase 5 cache).
- **NEW `forged/packaging.py`:** write `requirements.txt` + learner-facing `README.md` (what it teaches, who for, env setup, how to run) into the run dir; add both to `RETAINED_FILES`.
- **[orchestrator.py](../../forged/orchestrator.py) / graph finalize:** call packaging on completion.
- **Delegate:** `code-architect` (interfaces) → `tdd-guide` → `doc-updater` (README template + update output-contract docs).
- **Validate:** `pytest tests/pipeline/test_dependencies.py`; run dir contains `README.md` + `requirements.txt`; `pip install --dry-run -r requirements.txt` parses.
- **Complexity:** Medium.

### Phase 4 — Real agentic prose Reviser + dimensioned routing (P1, D2, D3 routing)
- **NEW `forged/pipeline/agents/content_reviser.py`:** LLM agent using `personas/reviser.md`; consumes notebook + student findings → rewritten notebook (mirror `code_author` output/parse/fallback shape).
- **[graph.py:145-154](../../forged/pipeline/graph.py#L145-L154):** add `content_reviser` node + edge `content_reviser → executor`; route `CONTENT_QUALITY → content_reviser`.
- **[router.py:104-109](../../forged/pipeline/router.py#L104-L109):** map dimensioned scores → stages; revisit reviser budget; preserve termination invariants.
- **Delegate:** `architect` (graph rewire + budget/loop invariants) → `tdd-guide` → `code-reviewer` + `python-reviewer` (high-risk control flow).
- **Validate:** offline graph tests (mocked LLM) — `CONTENT_QUALITY` produces a *new* notebook version and re-grades; budget still terminates; no infinite loop.
- **Complexity:** **High** (control-flow change).

### Phase 5 — Default environment provisioning + cache (rest of P0, D1)
- **[executor.py](../../forged/pipeline/agents/executor.py):** build/reuse a per-run venv from `requirements.txt`, keyed by the Phase-3 requirements hash (content-addressed cache → download heavy deps once); register the kernel; execute against it. Enforce install timeout, size cap, allow-list. Failure to install essential deps → honest non-acceptable (Phase 2 gate), never green-hollow.
- **[cli.py](../../forged/cli.py):** thread provisioning + honest exit codes; surface cache hits/misses and install failures.
- **Delegate:** `security-reviewer` (mandatory — running pip + arbitrary notebook code in a subprocess) → `build-error-resolver` if env wiring breaks; `verify`/`run` skills for the real E2E.
- **Validate:** dev/CI tests use a **tiny** dep (not torch) to exercise venv+cache; then **one** real end-to-end `forged agentic` on a tiny topic + cheapest viable model to confirm cells execute for real and the notebook is non-hollow.
- **Complexity:** **High** (subprocess, network, security, caching).

### Phase 6 — Docs, regression, close-out
- Update this doc's status to *implemented*, refresh `DEVELOPMENT.md`, `TODO.md`, `README.md` output contract, and `07-agentic-pipeline-status.md` known-limitations. **Delegate:** `doc-updater` + `update-docs`. Then `/code-review` + `/quality-gate` across the full diff; `checkpoint`.
- **Complexity:** Low.

---

## Part IV — Agent & skill delegation

| Phase | Lead agent(s) | Skills | Rationale |
|---|---|---|---|
| Pre | `architect` (1 shot, read-only) | — | Confirm graph + provisioning architecture once |
| 1 | `silent-failure-hunter`, `tdd-guide`, `python-reviewer` | `test-coverage`, `python-review` | Audit-then-fix swallow sites; rubric is logic-heavy |
| 2 | `architect`, `tdd-guide`, `python-reviewer` | `python-review`, `quality-gate` | Cascade placement; pure deterministic logic |
| 3 | `code-architect`, `tdd-guide`, `doc-updater` | `update-docs` | Interfaces + README templating |
| 4 | `architect`, `code-reviewer`, `python-reviewer` | `code-review` | High-risk control-flow rewire |
| 5 | `security-reviewer`, `build-error-resolver` | `build-fix`, `verify`, `run` | Subprocess + pip + cache = security/build risk |
| 6 | `doc-updater` | `update-docs`, `code-review`, `quality-gate`, `checkpoint` | Close-out |

**Delegation discipline (cost):** one architect pass total (not per phase); reviewers run **once per phase on the diff**; `silent-failure-hunter` runs once in Phase 1. No speculative spawning.

---

## Part V — Cost control

1. **Offline-first.** Phases 1–4 developed/tested with mocked LLMs (repo already has ~292 offline tests). Zero API spend through Phase 4.
2. **Tiny-dep testing for provisioning.** Phase 5 venv/cache logic is exercised with a small package, not torch.
3. **Content-addressed cache (mandatory for D1).** Heavy deps downloaded once, reused across all runs — the single biggest cost lever now that provisioning is default-on.
4. **One paid E2E per phase boundary** on a tiny topic + cheapest viable model — never a model matrix during dev.
5. **Free local gates** (`ruff`, `mypy`, `quality-gate`) before any paid agent review.

---

## Part VI — Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Default-on provisioning cost/time (torch ~2 GB per run) | High | High | Content-addressed venv/wheel cache keyed by requirements hash; size cap + timeout + allow-list |
| Running pip + notebook code in subprocess | Medium | High | `security-reviewer` mandatory; per-run isolated venv; package allow-list |
| Graph rewire causes infinite loop / budget regression | Medium | High | architect review of invariants; offline termination tests first |
| Rubric scoring destabilises existing accept logic | Medium | Medium | Keep `failure.py` docstring table authoritative; golden-fixture tests incl. localLLM hollow notebook |
| Planner structured-deps block unreliable from LLM | Medium | Medium | Deterministic extractor with regex-on-prose fallback |
| Cache key collisions / stale env reuse | Low | Medium | Hash full resolved requirement set + Python version; invalidate on mismatch |

---

## Part VII — Sequencing & complexity

```
Pre: architect (graph + provisioning)
  └─► P1 honest signals + rubric ──► P2 structural gate ──► P3 deps + deliverable
        (offline)                      (offline)             (offline)
                                                                 │
                                                                 ▼
                                                  P4 ContentReviser (graph) ──► P5 provisioning + cache ──► P6 docs
                                                       (offline tests)              (1 real run)
```

**Overall complexity: Large.** De-risked into four cheap offline phases, then the paid provisioning phase, then close-out.

---

## Part VIII — Acceptance

- [x] A hollow / all-skipped notebook classifies **non-acceptable** (P0/P5). *(Phase 2)*
- [x] Failed student call is a distinct signal, never a content score (P2). *(Phase 1)*
- [x] Student emits dimensioned rubric scores; composite drives the quality threshold (P2/D3).
      *(Phase 1; per-dimension **routing** to different stages is Phase 4.)*
- [ ] `CONTENT_QUALITY` produces a genuinely rewritten notebook and re-grades (P1/D2). *(Phase 4)*
- [x] Every run dir contains a learner-facing `README.md` + `requirements.txt` (P6). *(Phase 3)*
- [ ] Provisioning runs by default, reuses a content-addressed cache, and is bounded (D1). *(Phase 5)*
- [x] Degradations are visible in `SUMMARY.md`; honest exit codes preserved (P4). *(Phase 1)*
- [~] `pytest tests/` green (363 passed); `ruff` + `mypy` clean — **maintained per phase**;
      re-verify at each subsequent phase.
- [ ] Docs updated; this file marked *implemented* (final close-out, Phase 6).

---

## References

- `07-agentic-pipeline-status.md` — current agentic pipeline + known limitations
- `08-stage-specific-models.md` — model resolution
- `09-langfuse-tracing.md` — tracing
- Analysed run: `runs/localLLM/`
