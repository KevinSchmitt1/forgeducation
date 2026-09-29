# Lane 8 — UI frontend v1: local BYOK front door (CODE, additive)

**Branch:** `feat/ui-frontend` · **Type:** code, additive · **Depends on:** Lane 7 (✅ #59)
**Status:** ✅ **MERGED #63** (2026-09-29); Docker build not yet run. Green (935 passed, 90% cov) +
*exercised* + driven in a real browser against the fake LLM (`tests/ui/screenshots/`); *not
validated* (no paid run — that is Lane 10). **Remaining for the next agent (see "Handover" below).**
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `docs/architecture/25-ui-exploration.md`
in full (scope, stack recommendation, first-implementer plan steps 2–4, open questions) and
`docs/architecture/19-*.md` (build from a saved plan) first.

## Why this lane exists
Doc 25 decided **BUILD, scoped**: a local, single-tenant, bring-your-own-key web front door that
composes the run inputs, lets the user edit the plan at the cost gate, and launches the run. Lane 7
landed the backend seam (`course_from_dict`, `apply_adjustment`). **This lane builds the usable UI on
top of it — and it is now on the critical path:** the paid artifact-lesson run is gated on a usable UI
(decision 2026-09-29, `TODO.md`), so the paid run exercises the product a user actually touches.

## Scope (doc 25 first-implementer plan, steps 2–4)
1. **Thin service layer** (e.g. `forged/service.py`): `plan(inputs) -> plan-dict`,
   `apply_adjustment(plan, instruction) -> plan` (classification via `PlanAdjuster`, application via
   Lane 7's `apply_adjustment`; `replan` → the existing re-plan call), `build(plan, inputs) -> run_dir`.
   Reuse `forged/cli.py`'s existing plan/build functions — do not fork pipeline logic. If `cli.py`
   needs a small refactor to expose them, keep it behaviour-preserving and tested.
2. **v1 app — Gradio (default) or Streamlit**, pick one and say why in the PR:
   - typed input authoring for `LearnerProfile` + `TopicSpecification` (`forged/models.py`):
     dropdowns for the enums, add/remove rows for the lists, validation errors shown in-UI;
   - plan preview: modules, per-module lesson mode, cost estimate, fidelity notes — both the
     **1-module** and **N-module** shapes (doc 25 open question);
   - plan edits via the `PlanAdjuster` ops (merge / drop / reorder / force_single / set mode /
     guided re-plan), confirm / cancel;
   - launch `build(confirmed_plan)` — default to an **in-container subprocess** (doc 25); show the
     run dir and point at Langfuse for live watching (live streaming is **out of scope**).
   - BYOK settings field: key held **in memory only** and handed to the build/plan process via its
     environment — **never written to disk, never logged, never in a trace payload.** Test this.
3. **Entry point:** `forged ui` (subcommand in `cli.py`, following the "Add a CLI command"
   recipe in `CLAUDE.md`) or `python -m forged.ui`; UI deps as an optional extra (`pip install
   .[ui]`) so the CLI stays lean.
4. **Dockerfile** (+ `.dockerignore`): single-tenant image, `docker run -p … ` → localhost app;
   document it in `README.md`. Note: `[tool.setuptools] packages` currently omits
   `forged.curriculum` — a non-editable install (what Docker does) may be broken; verify and fix.

**Out of scope (by decision, doc 25):** live-run streaming (Lane 2 / Langfuse), notebook reading
(Jupyter), multi-tenant hosting/auth, a JS frontend, a second provider layer (doc 24 owns that).

## Files you own (collision map)
- New: `forged/service.py`, `forged/ui/…`, `Dockerfile`, `.dockerignore`, `tests/ui/…`,
  `tests/test_service.py`; edits: `forged/cli.py` (new subcommand / small extraction),
  `pyproject.toml` (optional extra + packages list), `README.md` (UI section), this brief.
- **Do NOT touch** `personas/`, `forged/pipeline/` (Lane 9 is in flight there), `router.py`,
  `failure.py`, `graph.py`, `mode.py`, `reviser.py`.
- **Do NOT edit** `TODO.md` or `docs/lanes/README.md` — the coordinator owns those while two lanes
  run in parallel. Update only this brief's **Status** line.

## Constraints (beyond the shared ones in CLAUDE.md)
- **No paid/network LLM calls** — not in tests, not in e2e, not while exercising. Stub the LLM
  (the planner call is cheap but billable; the paid run is the user's decision, after this lane).
- Immutability as everywhere: the service returns new plan dicts/objects, never mutates.
- Validate every UI input at the boundary (`course_from_dict` already raises locating errors).

## Verification (by deliverable — a UI is the most vertical-hungry deliverable)
- Unit tests for the service layer (plan → edit → confirm round-trip with a stubbed LLM; key never
  persisted/logged).
- **Driven in a real browser (Playwright):** start the app, fill the form, get a (stubbed) plan,
  apply an edit, confirm, reach the launch step. Screenshot key states. This is the lane's vertical
  rung — mocked-component tests do not count.
- **Exercised:** `python -m forged.cli ui --help` (or the chosen entry point) and a real launch.
  Docker: build and start the image once if Docker is available; if not, say so plainly.
- Three CI gates green (ruff / mypy / pytest ≥80%). Report which confidence level applies
  (green / exercised / validated) — see "Verification discipline".

## Done means
A user can `docker run` (or `forged ui`), paste their key, author inputs without YAML, see and edit
the plan, and launch a build — proven in a real browser against a stubbed LLM; PR opened.

## Handover (2026-09-29) — what is left before #63 merges

Resume with: *"continue lane 8 per `docs/lanes/08-ui-frontend.md`"* on branch `feat/ui-frontend`
(PR #63; master already merged in at `d64b1ee`).

1. **Docker, once** (the daemon was down when the lane was built; it is now up):
   `docker build -t forgeducation .` then
   `docker run --rm -p 127.0.0.1:7860:7860 -v "$PWD/runs:/app/runs" forgeducation forged ui --host 0.0.0.0 --fake-llm`
   and drive it: either point the Playwright e2e at the container, or at minimum load the page and
   click Plan → Confirm → Launch (dry run). Check the kernel is registered in the image
   (`docker run --rm forgeducation jupyter kernelspec list`) and that `runs/` is writable by uid 1000.
   Fix anything found in `Dockerfile`/`.dockerignore` only. Record the result in the PR body.
2. **Confirm remote CI is green** on #63 (`gh pr checks 63`); CI installs `.[dev]`, which pulls in
   gradio, so the UI tests run there (the browser e2e skips — no Playwright in CI).
3. **Do not merge on green alone** (CLAUDE.md norm 3): the user merges after reviewing; the paid run
   (Lane 10) is the validation.

Known small follow-ups (backlog, not blocking): "Check status" reports a pid the service did not
launch (e.g. after a UI restart) as running; Gradio is pinned `<6` (`css=`/`show_api=` are
deprecated there); the wheel/package-data gap is Lane 11.
