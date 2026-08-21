# TODO — forgeducation Roadmap

> **▶ Resuming work?** This file is the cold-start brief — current status, what's shipped, what's
> in flight, what's next. See [`CLAUDE.md`](CLAUDE.md) for repo conventions and architecture
> orientation (durable, not state); doc ownership is defined there under "Documentation".

---

## 🎯 STATE RIGHT NOW (2026-08-13) — the first artifact lesson ran, and failed informatively

Credits are back. A real single-lesson `learn` run happened
(`runs/20260813-201647_create_and_validate__github_co/`) on a GitHub-Copilot-config topic. It
produced **no acceptable notebook** — but it validated three things that had never been exercised
and produced a precise, reproducible diagnosis. **Full analysis:
[`docs/architecture/20-artifact-lessons-that-author-documents.md`](docs/architecture/20-artifact-lessons-that-author-documents.md).**

**What the run proved (previously unvalidated):**

| Thing | Result |
|---|---|
| Provisioning preflight (#33) | ✅ no provisioning failure; the run reached `code_author` and executed notebooks |
| One CLI front door (#35) | ✅ the only way in; plan gate → single-lesson branch worked |
| Planner picks `artifact` for a non-computational topic (docs 17/18) | ✅ 1 module, `mode: artifact`, correctly |
| An `artifact` notebook that builds and validates | ❌ **this is the failure** |

**What failed, in one line:** an instruction file for a coding agent is mostly code examples, so
the notebook embedded Markdown containing Python docstrings inside a Python triple-quoted literal,
and the docstring closed the literal. Four `code_author` iterations, four syntax failures, budget
exhausted. 1016.7s, 172,247 tokens.

**Accepted changes (doc 20) — status as of 2026-08-16:**

| | Change | Kind | Status |
|---|---|---|---|
| C1 | Name the delimiter collision in the revision brief | deterministic, free | ✅ `master` (#41) |
| C2 | Teach `code_author` `%%writefile` | persona | ✅ `master` (#41) |
| C3 | Plan-time **verifiability criterion** — explicitly **not** a blacklist | persona | ✅ `master` (#42) |
| C4 | Treat `finish_reason='length'` as recoverable | code | ✅ `master` (#42) |
| C5 | `code_author` sees its notebook and **patches failed cells** | code | 🔄 **PR #45** |
| C6 | Non-convergence makes the loop **aware** ("look for a systematic cause") | brief text | ⬜ folded into doc 22 (R8) |
| C7 | Iteration-aware cost estimate | code | ⬜ **low priority** |

**Doc 22 (the review itself) — status as of 2026-08-21:** R1 (fatal-dimension gate) and R2
(critic finding budget) are built and offline-validated; R5 is unblocked and next; R3, R4,
R6, R7, R8 not built. Per-item table lives in doc 22 Part IV.

**None of it is validated by a paid run yet.** All of it is validated offline against the four
failing notebooks the run left behind (see below) — which is a real level of confidence, but not
the same one. The next artifact-lesson run is what proves the loop actually escapes.

### What the offline validation actually showed

**C1's detector, measured on the real corpus** (precision mattered more than recall — a diagnosis
attached to every `SyntaxError` teaches the reader to ignore it):

| notebook | failed cells | fires on | correct |
|---|---|---|---|
| v0 | 4, 7, 9, 12, 14, 17, 19, 21 | **7, 12** | ✅ not 4 — a genuine stray indent |
| v1 | 16 | **nothing** | ✅ runtime `SystemExit`, parses fine |
| v2 | 12, 17, 20 | **12** | ✅ |
| v3 | 7, 9, 12, 14, 17, 19, 22 | **7, 17** | ✅ |

v0 was **already colliding** at cells 7 and 12 — the interpreter reported the stray indent first,
so it was invisible. Three of four iterations would have been told the mechanism, from the first.

**C5's premise, executed through the production code path** (`patch_from_json` → `apply_patch` →
run the notebook):

```
cells: 26 (was 26) | untouched preserved byte-for-byte: 23/23
failed cells: [9, 14, 19]   (original run: [7, 9, 12, 14, 17, 19, 22])
  OK .github/copilot-instructions.md  3,058 bytes
  OK AGENTS.md                        3,639
  OK tools/validate_agent_docs.py     8,265
```

**Every syntax failure gone, all three artifacts produced, 3 of 26 cells touched.** Four full
rewrites and 74K tokens never got there.

The 3 that remain are **content, not structure**, from two roots — both now feeding doc 22:
a **self-referential validator** (the document forbids hardcoded secrets, names `PASSWORD` doing
so, and the generated validator flags any `PASSWORD` as a leak) and an under-filled `AGENTS.md`.

### Two constraints found by doing it (both are in the persona now)

- **`%%writefile` cannot create parent directories** — an earlier cell must make them.
- **A replaced cell loses everything it defined.** The original cell 7 held the `dedent` import
  and bound `instructions_path`; a naive replacement killed cell 12 with `NameError`. An author
  can only notice this by **seeing the whole notebook** — which is exactly what C5 adds, and the
  sharpest argument for its design.

**Two decisions worth not re-litigating** (both recorded with reasons in doc 20):

> **No syntax gate.** Execution already collects *every* failing cell and also finds runtime errors
> a parse cannot. Kernel time costs no tokens; an extra iteration costs a gpt-5 notebook.

> **No blacklist of forbidden operations.** Same failure mode as the package allow-list (#31):
> simultaneously too narrow and too broad. C3 is a criterion the planner applies, not a list it is
> checked against. Related: the program needs **no GitHub access** — the notebook already creates
> local scratch repos with `git init` successfully; only the *unqualified* "commit to the
> repository" objective broke it.

## ▶ NEXT — pick up here

1. ~~Merge the open PRs #45 (C5 patching) and #46 (doc 22 design)~~ — ✅ both on `master`
   (2026-08-16), along with #47. All merged feature branches deleted local + remote.
2. ~~**Build R1 + R2 from doc 22**~~ — ✅ done 2026-08-21, offline-validated against the real
   corpus. **Doc 22's stated R1 criterion turned out to be un-failable** (all four iterations
   were already not-acceptable via the execution-failure route, before any rubric is read), so
   the validation is a counterfactual instead: *what would this rubric produce had the notebook
   run clean?* v1's 82/100 goes **acceptable → test_failure**, and v0/v2/v3 stop being handed to
   the prose reviser on a correctness of 40–50. Full table + reasoning in doc 22's
   "Implementation note".
3. **Doc 22's open question 1 is settled** (Kevin, 2026-08-16): R5's goal-fit/necessity
   dimension is a **separate verdict beside the rubric**, not a sixth dimension — averaging is
   what hid the problem, so the fix must not be more arithmetic. R5 is now unblocked; **R1 was
   its prerequisite and is done.**
4. **Next build items, in doc 22's order:** R5 (the founding "code-heavy, not practical"
   complaint), then R6 → R7 (the `critique_digest`, then the informed remake), then R3/R4/R8.
5. **Then a paid artifact-lesson run**, to validate C1–C5 *and* R1+R2 for real. Use
   `--plan-only` first to confirm the mode for cents (see "New loose ends"). R2 is the one that
   most needs it: the tests prove the instruction is present, not that the critics obey it.

### Shipped since (2026-08-08 → 08-16)

| Change | Where |
|---|---|
| Provisioning preflight — venv built between planner and code_author | ✅ `master` (#33) |
| One CLI front door; linear engine deleted | ✅ `master` (#35) |
| Repo-wide guard against billable calls in tests + entry-point smoke test | ✅ `master` (#37) |
| Plan display tells the truth (`--max-modules` pricing; one plan renderer) | ✅ `master` (#38) |
| Design: build from a saved `course_plan.json` (doc 19) | ✅ `master` (#39) |
| Design + docs: the artifact-lesson failure analysis (doc 20) | ✅ `master` (#40) |
| **C1 + C2** — collision named in the brief; `%%writefile` idiom | ✅ `master` (#41) |
| **C3 + C4** — verifiability criterion; truncation recovery | ✅ `master` (#42) |
| Design: patch-don't-regenerate (doc 21) | ✅ `master` (#43) |
| Doc 21's offline check run — C5's premise holds | ✅ `master` (#44) |
| **C5** — `code_author` sees its notebook and patches it | ✅ `master` (#45) |
| Design: a review that points at the fix (doc 22) | ✅ `master` (#46) |
| **doc-22 R1** — a fatal rubric dimension gates the verdict instead of averaging into it | 🔄 in flight |
| **doc-22 R2** — critics stop re-reporting the execution report | 🔄 in flight |

**Config change worth knowing (#42):** the `gpt-5-mini` stages went `max_tokens` 4096 → 8192.
Every one of them already exceeded 4096 once reasoning is counted (planner 4,208, student
~5,135, reviewer ~5,592) — OpenAI counts reasoning against `max_completion_tokens`. A ceiling is
a cap, not a target, so this prevents truncation without raising spend.

**PR #37 found 9 tests that had been making real paid API calls on every local run** (CI has no key
configured, so the cost was local-machine only). Suite runtime dropped from minutes to ~15s. The
accidental-spend hole from 2026-08-08 is now closed by an autouse fixture on `LLMClient.complete`,
with `@pytest.mark.live` as the explicit opt-in.

**Two git lessons from getting these merged, both mine:**

> **Don't open stacked PRs here.** #34 was opened with base `feat/provisioning-preflight` instead of
> `master`. Merging it merged into that feature branch; `master` was updated separately by #33 and
> never received the consolidation. GitHub reported #34 as MERGED — into the wrong place. It took a
> fresh PR (#35) against `master` to actually land it. **A MERGED badge is not proof code reached
> `master`; check `git ls-tree origin/master`.** Either hold related changes on one branch, or wait
> for the first to land and rebase the second onto `master`.

> **Squash-merges leave duplicate commits on feature branches.** After #32 was squash-merged, both
> branches carried a copy of its commit and GitHub reported a phantom conflict. Rebase onto
> `origin/master`; don't re-merge.

## 🎯 THEN — RE-RUN THE DOC-18 VALIDATION (criteria 3–5 still unmeasured)

The lesson-mode debias **works** and is proven across two runs. What is *not* yet known is whether
the resulting notebooks are actually better.

> **Update 2026-08-13.** The provisioning blocker is gone — the run that day reached `code_author`
> and executed notebooks with no provisioning failure at all, so criterion 5 now has positive
> evidence for a single lesson. The blocker moved *downstream*: notebooks are now produced and then
> fail to run (doc 20). **Land C1–C3 before re-running this topic** — three of its four modules are
> `executable`, but module 0 is `artifact`, and it would hit the same delimiter collision.

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
| 3 | Subject stays concrete instead of drifting to computable proxies | ⬜ **unmeasured** — still no *acceptable* notebook |
| 4 | Code share drops from the 76–89% band | ⬜ **unmeasured** — needs a built mixed course |
| 5 | All modules provision | ✅ **positive evidence** — the 2026-08-13 single-lesson run provisioned and executed with no failure |

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

### Known loose ends

**All five items in this section were closed by PR #37 (2026-08-13).** Kept as a record of what
they were, because each cost something before it was fixed.

- ~~**CI smoke test for the entry point**~~ — ✅ `tests/test_entrypoint_smoke.py` ships. It spawns a
  real `python -m forged.cli` subprocess: bare `--help`, per-command `--help`, `pipelines`, a blank
  `--topic` (usage exit 2), an unknown command — asserting exit codes and that no traceback prints.
  **Verified to have teeth rather than assumed:** reintroducing the #30 bug shape (`main()` calling a
  helper defined below the `__main__` guard) leaves the 25 import-based CLI tests green, ruff clean
  and mypy clean, while these fail.
- ~~**Nothing repo-wide stops a test from making a live paid call**~~ — ✅ an autouse fixture in
  `tests/conftest.py` replaces `LLMClient.complete` (the single funnel every billable call goes
  through) with one that raises, naming the model it refused. `@pytest.mark.live` is the explicit
  opt-in. **Guarding the constructor, as originally suggested here, was the wrong seam** — it is
  credential-free by design so the offline suite can build real agents, and guarding it would fail
  hundreds of tests that never spend anything.
  **It immediately found 9 tests reaching the real API on every local run** in
  `tests/pipeline/test_agents_concrete.py`. They passed either way: with a key they took the real
  path, without one they took CodeAuthor/Student's degrade-to-fallback path — so the spend was
  silent, and `conftest.py` loads `.env`, so a key was always present locally. Suite runtime dropped
  from minutes to ~15s.
- ~~**`setup_logging` accumulates handlers**~~ — ✅ handlers it installs are tagged, and each call
  detaches and closes its own. Only ours are swept, so pytest's capture and a host application's
  handlers survive (the naive `root.handlers.clear()` would have destroyed them; a test pins it).
  **Still only test-green:** the bug needs 2+ modules to manifest, so a course run is what validates
  it. `forged/logging_config.py` had no test file at all before this.
- ~~**CI never invokes the CLI the way a user does**~~ — ✅ closed by the smoke test above.
- ~~**`personas/code_author.md:22` still calls `conceptual` "(rare)"**~~ — ✅ removed, along with
  `executable`'s "(the default — most lessons)". `planner.md` states outright that "None of the
  three is a default, and none is a fallback"; `code_author.md` was the last persona contradicting it.

### New loose ends (2026-08-16)

- **Nobody sees more than one revision brief.** Verified across `code_author.py`,
  `planner.py`, `content_reviser.py`: every agent reads exactly
  `revision_brief_v{iteration - 1}`. So a rewrite at iteration 3 knows nothing of what
  iterations 0–2 revealed — the mechanism behind quality going 74 → 82 → 74 → **71**.
  Tracked as D5/R6 in doc 22 (the `critique_digest`).
- **`content_reviser` has the same never-sees-its-own-output shape as `code_author` had.**
  Almost certainly wants C5's change too; deliberately deferred until C5 is validated by one
  real run before the pattern is copied. Doc 22, open question 3.
- **The 2026-08-13 artifacts are the regression corpus and `runs/` is gitignored.** The four
  failing notebooks are what C1 and C5 were validated against. If that directory is pruned
  (`forged clean`), the evidence for every offline check in docs 20–22 goes with it. Worth
  copying somewhere durable before the next cleanup.

### New loose ends (2026-08-13)

- **The cost estimate models a clean pass, not a revision loop.** `gate.py` assumes
  `EST_TOKENS_PER_LESSON = 100_000`; the 2026-08-13 run used **172,247** because it iterated four
  times. Tracked as C7 in doc 20, low priority.
- **`--plan-only` cannot be built.** A probe produced exactly the wanted plan (1 module,
  `mode: artifact`) and there was no way to build *that* plan — the build path always re-plans, and
  the planner is non-deterministic. Design: `docs/architecture/19-build-from-a-saved-plan.md` (PR
  #39). The missing piece is `course_from_dict`; `model.py` has `course_to_dict` and no inverse.
- **`conceptual` has never been observed firing.** Five planning calls, including two probes on
  deliberately non-computational topics ("when should I use Copilot agent mode vs chat vs inline
  completions") — both returned `artifact`. Doc 18 debiased mode selection and proved a *mix* is
  reachable; it did not prove all three modes are. Cheap to keep probing with `--plan-only`.

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

### Cost findings — second data point (2026-08-13, 12 calls / 172K tokens)

The failed artifact run confirms the output/reasoning-dominated picture below and adds one
finding the earlier run could not show, because it never iterated four times:

| stage | model | calls | output | reasoning | total |
|---|---|---:|---:|---:|---:|
| code_author | gpt-5 | 4 | 49,950 | 16,512 | **74,044** |
| student | gpt-5-mini | 4 | 11,707 | 8,832 | 52,290 |
| reviewer | gpt-5-mini | 3 | 9,802 | 6,976 | 39,124 |
| planner | gpt-5-mini | 1 | 2,928 | 1,280 | 6,789 |

**The revision loop *is* the cost.** `code_author` alone is 43% of the run, and every one of those
four calls regenerated a whole notebook rather than patching the failing cells — which is why C5
(patch, don't regenerate) is the highest-value cost change available, ahead of `reasoning_effort`.
Input caching held up (`code_author` 46.2% cached); the critics still cache poorly (12–13%).

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
