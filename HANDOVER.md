# HANDOVER — next session start here

_As of 2026-06-26. Cold-start brief: read this + the files it names and you have full context.
When this session's work is superseded, update or delete this file._

## TL;DR
This session was a **cost investigation**, not curriculum work. We shipped **per-call token
observability** (PR #13, CI green) and used it to get the real shape of one lesson run's cost.
The headline: the bill is **output/reasoning-dominated**, not input-dominated — which **reverses**
the earlier "caching is the #1 lever" assumption. The curriculum-planner Phases 3–5 track is
**still the eventual roadmap** but was paused for this. Next session: Kevin's manual quality checks
(below), then the cheap cost/robustness follow-ups this run exposed, then back to curriculum.

## ▶ Do this first, in order
1. **Kevin's quality checks (manual, in progress):**
   - Re-review `runs/localLLM-r1-validate/lesson_notebook_v3.ipynb`.
   - Run a fresh notebook with the **same input** to validate the last pipeline changes (command below),
     then read through it.
2. **Confirm PR #13 merges** (`feat: per-call LLM token observability`) — CI is green; squash-merge,
   then delete the branch.
3. **Cheap cost/robustness follow-ups the R1 run exposed** (no paid run needed to *implement*):
   - **API-drift hardening.** The `localLLM_tokens_last` run produced a *real* LoRA adapter on
     `distilgpt2` but failed cell 12 on `TypeError: TrainingArguments.__init__() got an unexpected
     keyword argument 'evaluation_strategy'` (recent `transformers` renamed it to `eval_strategy`).
     code_author burned its whole fix budget without landing the rename. Fix at the source: have the
     planner **pin `transformers`** in `requirements`, and/or teach code_author the `eval_strategy`
     rename, so API drift stops eating the code-fix budget.
   - **Reasoning-cost lever.** Reasoning tokens are ~30% of a run (see below). The LLM client
     (`forged/llm.py`) doesn't set OpenAI `reasoning_effort`; adding a low setting on
     `code_author`/`reviser` is the single biggest controllable cost lever. Experiment + measure with
     the new `USAGE.md`.
   - **Caching headroom.** `code_author` already hits **47.5% input caching**; the critic stages cache
     **0%**. Reordering critic prompts so the stable prefix (persona + context) comes first, volatile
     notebook content last, should unlock auto-caching there too.

## 📊 What the token meter showed (one R1 run = `localLLM_tokens_last`)
`USAGE.md` per run now reports input/output/**cached**/**reasoning** per stage. The R1 run (11 calls,
102,240 tokens):
- **Output 55,787 > Input 46,453.** Of the output, **31,040 is reasoning** (~30% of the *entire* run) —
  invisible before this feature.
- **code_author (gpt-5):** 4 calls, 47,980 tokens (47% of the run), **47.5% input-cached**, 17,088 reasoning.
- **critics (gpt-5-mini):** reviewer/student/planner — **0% cached** despite reviewer's 4 calls / 19.5K input.
- Implication: the earlier "input-dominated, caching is #1" advice was **wrong**. Real levers, ranked:
  **(1) cut gpt-5 reasoning, (2) restructure critic prompts for caching, (3) cheaper cheap-stage model.**

## ⏸ Decisions parked this session (don't re-litigate)
- **Subscription / "Claude Pro" path (Kevin's cost question): deprioritized.** Subscriptions don't
  permit programmatic API access; the only bridge (shell out to the `claude` CLI on a Max OAuth token,
  pycastle-style) caps out and is ToS-grey for a product. The bill being output/reasoning-heavy makes
  subscriptions an even worse fit. The cheap win is `reasoning_effort`, not a platform migration.
- **Local Ollama routing: NOT viable on this machine.** mistral 7B (4 GB) crashed Kevin's **8 GB M1**
  (weights + large-context KV cache + VS Code + pipeline → swap death). Even a working ≤1.5 GB model
  can't do the expensive `code_author` stage at acceptable quality, so it doesn't touch the real cost
  driver. Do not run Ollama here. (Memory: `ollama-crashes-this-machine`.)

## 🔁 Reproduce the run (Kevin's step 2 — "new notebook, same input")
```bash
.venv/bin/forged agentic \
  --topic "How to setup and train local LLMs on Apple Silicon M1" \
  --learner-profile templates/examples/kevin_learner.yaml \
  --run-dir runs/<new-name>
# Prefer provisioning (drop --no-provision) so the planner can pin a transformers version that still
# has `evaluation_strategy` — that was the only thing that broke the last run. --no-provision uses the
# base env's newer transformers and will hit the eval_strategy TypeError again.
```
Paid (gpt-5). One run ≈ 100K tokens, ~85 min wall-clock at 3 revision iterations. After it lands, read
`runs/<new-name>/USAGE.md` (cost shape) + `SUMMARY.md` (fidelity + outcome).

## Files this session touched
- `forged/usage.py` — **new**: `UsageRecord`, thread-safe `UsageLedger` (keyed by run_id), `build_report`,
  `write_usage_report` → `usage.json` + `USAGE.md`.
- `forged/llm.py` — `_usage_details` now also pulls cached + reasoning tokens; `_record_usage` records
  into the ledger inside `complete()` (covers all paths, no signature changes).
- `forged/cli.py` — `_cmd_agentic` writes the report after the run.
- `tests/test_usage.py` (new), `tests/test_cli_agentic.py` (usage.json assertion).

## After the quality checks — back to the tech roadmap
The eventual track is unchanged: **curriculum planner Phases 3–5 + the cli deliverable-writer cleanup**
(`docs/architecture/13-curriculum-planner.md`, and TODO.md → "Next Up"). The cost follow-ups above are
quicker wins to fold in first if you want the per-run bill down before the (paid) full course run.

## Conventions that bit us (don't repeat)
- **Git:** push uses SSH which has no key in the agent shell — push via `gh auth setup-git` + an explicit
  HTTPS URL (`git push https://github.com/KevinSchmitt1/forgeducation.git <branch>`). `gh` is installed +
  authenticated. Feature branch + PR, no attribution trailer, never push red.
- **`--no-provision` + a torch/transformers topic = API-drift failures** (base env has *newer* libs than
  the lesson code expects). Provision for a clean validation run.
- **CI gates (all three, every PR):** `.venv/bin/ruff check forged tests`, `.venv/bin/mypy`,
  `.venv/bin/python -m pytest --cov=forged --cov-fail-under=80`.
- `runs/` is gitignored — run artifacts (incl. `usage.json`/`USAGE.md`) won't show in `git status`.
