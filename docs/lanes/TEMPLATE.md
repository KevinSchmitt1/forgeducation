# Lane NN — <title> (<DELIVERABLE TYPE>)

<!-- Copy to docs/lanes/NN-<slug>.md. `scripts/start_lane.sh NN` reads the Branch line below —
     keep its exact shape: **Branch:** `type/name`. Add a row to docs/lanes/README.md. -->

**Branch:** `<type>/<name>` · **Type:** <code | persona | docs | validation> · **Depends on:** <…>
**Status:** not started.
**Process:** see "Lane workflow" and "Human checkpoints" in root `CLAUDE.md`. Read <docs> first.

## Why this lane exists
<the problem, in the user's framing where possible; link the design doc>

## Scope
1. <…>

## Files you own (collision map)
- <files this lane may edit>
- **Do NOT touch** <hot files other lanes own>.
- **Do NOT edit** `TODO.md` or `docs/lanes/README.md` — coordinator-only while lanes run in
  parallel. Update this brief's **Status** line and **Checkpoint log** only.

## Constraints
- <cost / immutability / no paid calls without a SPEND checkpoint / …>

## Human checkpoints
Post each with `scripts/checkpoint.py` and end the turn (CLAUDE.md → "Human checkpoints").
- **CP0 kickoff:** <the decisions the user must make before code — e.g. approach (a) vs (b)>
- **CP1 demo:** <what the user will try hands-on, e.g. "`forged ui --fake-llm`, plan a course,
  drop a module"> — or "n/a (docs-only lane)"
- **CP2 merge:** review packet (standard contents).
- **SPEND:** <each billable call this lane may need, with an estimate> — or "none".

## Verification (by deliverable)
- <the rung this deliverable must reach: review / exercised / real browser / live-replay / validated>
- Three CI gates green (ruff / mypy / pytest ≥80%).

## Done means
<one paragraph: observable end state; PR opened; CP2 answered>

## Checkpoint log
<!-- one line per answered checkpoint: YYYY-MM-DD · CPn · the user's decision -->
