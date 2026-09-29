# Lane 10 — The paid artifact-lesson run, through the UI (VALIDATION, user-consented)

**Branch:** `docs/paid-run-via-ui` (findings doc only) · **Type:** validation run + findings doc ·
**Depends on:** Lane 8 merged (#63), Lane 9 merged (✅ #62), Lane 6 merged (✅ #60)
**Status:** not started — **blocked on #63 merging and on the user's explicit go-ahead to spend.**
**Process:** see "Lane workflow" and "Verification discipline" in root `CLAUDE.md`. Read `TODO.md`
(▶ NEXT §2 — *what to read in the findings*), doc 22 (R1/R2/R5/R6/R7), doc 23 (author split) and
doc 20 (the 2026-08-13 failure this run re-attempts) first.

## Why this lane exists
Everything since 2026-08-13 — C1–C5, doc 22's R1/R2/R5/R6/R7, the author split (doc 23) — is
green and offline-validated but **not validated by a real run**. The decision of 2026-09-29 gated
that run on a usable UI so it exercises the product a user actually touches. Lane 8 delivered the
UI; this lane is the one binding validation gate. It is worth more than the next feature.

## This lane is not autonomous
**It spends money.** An agent prepares and records; **the user supplies the key and says go.** The
agent must not paste a key, set `OPENAI_API_KEY`, or click *Plan*/*Launch* in real mode without an
explicit, per-run instruction from the user. Keep it to **one** paid build (CLAUDE.md cost discipline).

## Scope
1. **Free preparation (no key):** on `master` after #63, run `forged ui --fake-llm` and the browser
   e2e once to confirm the merged UI works; build + start the Docker image if the user wants the run
   in Docker (recommended: it is the documented distribution path).
2. **Cheap live-replays first (cents, needs the user's OK + key):** the Lane 1 harness
   `pytest -m live tests/pipeline/test_live_corpus_replay.py` — covers R2/R5 and the owed R7 remake
   behaviour (doc 22) and Lane 9's author persona, before the expensive run.
3. **The run (user drives the UI, agent watches Langfuse / the launch log):** the artifact topic
   from 2026-08-13 (doc 20; `templates/examples/kevin_learner.yaml` for the profile). In the UI:
   author inputs → Plan (≈1 gpt-5-mini call) → check the module's mode is `artifact` → confirm →
   Launch. Cap with *Max modules* = 1 if the plan comes back as a course.
4. **Findings doc** `docs/architecture/26-paid-run-via-ui.md`: answer TODO NEXT §2's questions
   (R2 restated failed cells? R5 `goal_fit` right? R1 fatal-dimension refusals? R7 remake decision
   sensible? did the Artifact Author persona change the notebook?) **and** what the UI got wrong or
   made awkward when used for real. Findings, not just the verdict. Include cost/tokens (usage.json).

## Files you own (collision map)
- New: `docs/architecture/26-paid-run-via-ui.md`; this brief's Status line.
- Read-only everything else. Bugs found become **new lanes/briefs**, not fixes in this lane —
  except a trivial UI blocker that prevents the run itself (then: tiny fix on its own branch + PR).

## Human checkpoints
Post each with `scripts/checkpoint.py` and end the turn (CLAUDE.md → "Human checkpoints").
- **CP0 kickoff:** the topic + profile you will use, Docker or local, what the findings doc will
  answer, and the cost estimate for the whole lane.
- **CP1 demo:** after the free preparation — the merged UI works on `master` (`forged ui
  --fake-llm` + the browser e2e) and, if chosen, in the Docker image. The user clicks through once.
- **SPEND #1:** the live-replays (`pytest -m live …`), a few cents. **SPEND #2:** the one paid build
  through the UI — estimate from the 2026-08-13 run (≈170K tokens). Separate approvals.
- **CP2 merge:** the findings doc as the review packet — answers to TODO NEXT §2's questions, what
  the UI got wrong, cost/tokens, and which lanes it validated or not.

## Verification
This lane *is* the "validated" rung for Lanes 6, 8, 9 and doc 22. Report plainly which of those it
validated and which it did not.

## Done means
One paid run completed via the UI (or an honest record of why it could not), findings doc merged,
and a proposed TODO update handed to the coordinator (who owns `TODO.md`).

## Checkpoint log
<!-- one line per answered checkpoint: YYYY-MM-DD · CPn · the user's decision -->
