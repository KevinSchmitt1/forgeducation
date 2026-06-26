# HANDOVER — next session start here

_As of 2026-06-24. This is the cold-start brief: read this + the files it names and you have
full context. When this session's work is superseded, update or delete this file._

## TL;DR
The **curriculum planner (Half B)** is built through **Phase 2** and merged to `master`:
`forged course` decomposes an over-large topic into an ordered course of module lessons and runs
each through the (unchanged) agentic lesson pipeline, folding earlier modules' objectives into later
modules' prior knowledge. **Next task is a cleanup, then Phases 3–5.** Start the next session with a
**`/plan` phase** before writing code.

## ▶ Do this first, in order
1. **Run a `/plan` phase** for the cleanup + Phase 3/4 (the repo convention is plan-first; a design
   doc usually lands in `docs/architecture/`).
2. **Cleanup (the agreed first priority): extract the per-run deliverable writers out of `cli`.**
   - The orchestrator writes each module's outputs by reaching into **private** `forged.cli` functions
     `_write_agentic_summary` / `_write_final_notebook` / `_write_learner_package` via a **deferred
     import** inside `forged/curriculum/orchestrator.py::_write_module_deliverables` (to dodge a
     cli↔orchestrator load cycle). This is a layering smell and the functions are **patched out in unit
     tests**, so the real per-module writing only runs live.
   - Extract those three into a shared module (e.g. `forged/run_outputs.py`); update `cli._cmd_agentic`
     and the orchestrator to import from there. Behavior-preserving; keep `_cmd_agentic` tests green.
     Then the orchestrator's deliverable path can be unit-tested directly (remove the patch-out).
3. **Then curriculum Phases 3–5** — see `docs/architecture/13-curriculum-planner.md`:
   - **Phase 3 — course assembly:** index `README.md` (ordered modules + prerequisite cross-links) +
     aggregate `COURSE.md` surfacing per-module degradations/fidelity signals.
   - **Phase 4 — reactive safety net (R1 → planner → R1 loop):** when a module run still drops a
     capability (`ModuleResult.topic_fidelity` has non-empty `missing`), hand the overflow back to the
     `CurriculumPlanner` as a new module and run it; bounded by `--max-modules`. (Kevin's framing.)
   - **Phase 5 — close-out:** flip doc 13 to IMPLEMENTED; CLI polish.

## ⏸ Deferred to "later" (not now)
- **Live full course run (paid).** No real multi-module run has been executed. Est. **~$10–25, 1–3h**
  for the 6-module overarching course (each module provisions a torch venv). **Cheapest first proof:**
  `forged course --topic "…" --max-modules 1 --no-provision` — one real module to validate the whole
  chain (and exercise the un-tested deliverable-writing seam) before scaling up.
- **Dependency-aware parallel module execution.** Currently sequential. The modules form a DAG and only
  *objectives* (known at plan time) are folded into prior knowledge, so there's no hard data dependency
  forcing strict order — parallel is feasible later, capped by a concurrency limit. See doc 13 Part I.b.

## 💬 Open discussion for next session (Kevin raised, do not solve yet)
- **Cost / "Claude Pro subscription solution."** API usage (OpenAI gpt-5 for code_author/reviser is the
  expensive stage) is getting cost-prohibitive, especially now that one `forged course` run = N lesson
  runs. Kevin wants to discuss moving the program off pay-per-token API toward a subscription model.
  Bring options: provider/model swap (e.g. cheaper stages, Claude models, local Ollama for some stages),
  routing the expensive stages differently, caching, and what a subscription-backed path would actually
  look like for a programmatic pipeline. **This is a discussion, not a build task — surface trade-offs.**

## Map of what's merged (the honesty trilogy)
Three compounding features, all sharing the same term-coverage logic:
- **R1 — topic fidelity (lesson level):** never *silently drop* a requested capability.
  `docs/architecture/11-topic-fidelity-r1.md`; `forged/pipeline/fidelity.py`.
- **Learner orientation cell:** never *silently assume* a prerequisite — first notebook cell surfaces
  the planner's KNOWN/GAP map in plain language. `docs/architecture/12-notebook-orientation-cell.md`.
- **Curriculum planner (Half B), Phases 1–2:** never *drop across a course*, never *re-teach across
  modules*. `docs/architecture/13-curriculum-planner.md`.

## Files the next agent needs
- `docs/architecture/13-curriculum-planner.md` — the curriculum plan of record (phases, decisions, the
  Part IV data contracts, the cleanup gap).
- `forged/curriculum/` — `model.py` (CourseSpec/ModuleSpec/ModuleResult/CourseResult, `course_to_dict`),
  `planner.py` (CurriculumPlanner, gpt-5-mini), `fidelity.py` (`assess_course_fidelity`),
  `orchestrator.py` (`run_course`, `_augment_profile`, `_write_module_deliverables` ← the cleanup site).
- `personas/curriculum_planner.md` — the decomposition persona (emits JSON; union-coverage rule).
- `forged/cli.py` — `_cmd_course` (+ the three `_write_*` writers to extract); `_cmd_agentic` is the
  single-run lifecycle the orchestrator mirrors.
- `forged/context.py::build_context_block`, `forged/models.py::LearnerProfile` (the `prior_knowledge`
  fold), `forged/pipeline/graph.py::run_pipeline`, `forged/pipeline/state.py` (`TopicFidelitySignal`).
- `tests/test_curriculum_*.py`, `tests/test_cli_course.py` — current coverage (note the patched-out
  deliverable writer in the orchestrator tests).

## Conventions that bit us (don't repeat)
- **Git is autonomous** (commit/push/PR without asking) but: feature branch + PR, never to `master`,
  conventional commits, **no attribution trailer**, never push red. After merge, delete the branch.
- **Do NOT block-watch CI** (`gh ... --watch` / `until+sleep`) — the harness auto-backgrounds it and it
  looks like a hang. One-shot `gh pr checks`, or background explicitly with a heads-up. Same for the
  ~5–8 min full test suite. (See `CLAUDE.md` git bullet.)
- **CI gates (all three, every PR):** `.venv/bin/ruff check forged tests`, `.venv/bin/mypy`,
  `.venv/bin/python -m pytest --cov=forged --cov-fail-under=80`. TDD per change.
- **`gh` is installed + authenticated**; GitHub MCP is **not** — use `gh`.
