# docs/lanes — workstream briefs

This directory holds the **coordination brief for each lane** of the current effort. A "lane" is an
independent slice of work on its own **branch in this repo** (everything lives here — no external
worktrees, no sibling folders). Its brief states scope, file ownership (the collision map), the
verification rung it must reach, and its definition of done.

- **How to start or resume a lane** (branch setup, verification-by-deliverable, sync): see the
  **"Lane workflow"** section in the repo root `CLAUDE.md`.
- **To resume in a fresh session:** *"continue lane N per `docs/lanes/0N-*.md`"* — the agent checks
  out the lane's branch, reads the brief, and picks up from `git log` + the brief's **Status** line.
- **Project state / roadmap** lives in `TODO.md` (single source of truth), not here.

## Lanes

| Lane | Doc | Branch | Deliverable | Verification rung | Depends on |
|------|-----|--------|-------------|-------------------|------------|
| 1 · Vertical-confirmation harness | [01-vertical-harness.md](01-vertical-harness.md) | `feat/vertical-confirmation-harness` | code (owns `tests/`) | *is* the vertical rung | — · **MERGED #53** |
| 2 · Local observability | [02-local-observability.md](02-local-observability.md) | `feat/local-observability` | code | exercised + unit tests | — · **MERGED #57** |
| 3 · Author-identity split | [03-author-split.md](03-author-split.md) | `docs/author-split-design` | design doc → doc 23 | review | — · **MERGED #55** |
| 4 · SDK-as-provider | [04-sdk-provider.md](04-sdk-provider.md) | `docs/sdk-provider-design` | design doc → doc 24 | review | — · **MERGED #54** |
| 5 · UI grilling | [05-ui-exploration.md](05-ui-exploration.md) | `docs/ui-exploration` | decision doc → doc 25 (BUILD, scoped) | review | — · **MERGED #56** |
| 6 · Critique digest → remake (R6→R7) | [06-critique-digest-remake.md](06-critique-digest-remake.md) | `feat/critique-digest-remake` | code + persona | live-replay + offline corpus | Lane 1 ✅ · **MERGED #60** (R6 offline-validated; R7 live-replay owed) |
| 7 · UI backend seam | [07-ui-backend-seam.md](07-ui-backend-seam.md) | `feat/ui-backend-seam` | code, additive | exercised (`--plan-only` round-trip) | doc 25 ✅ · **MERGED #59** |
| 8 · UI frontend v1 (BYOK front door) | [08-ui-frontend.md](08-ui-frontend.md) | `feat/ui-frontend` | code, additive | real browser (Playwright, stubbed LLM) ✅ | Lane 7 ✅ · **PR #63 open** — Docker check left, then user merges |
| 9 · Author-split implementation | [09-author-split-impl.md](09-author-split-impl.md) | `feat/author-split` | code + persona | offline + exercised (live-replay owed → Lane 10) | doc 23 ✅, Lane 6 ✅ · **MERGED #62** |
| **10 · Paid run via the UI** | [10-paid-run-via-ui.md](10-paid-run-via-ui.md) | `docs/paid-run-via-ui` | validation run → doc 26 | *is* the validated rung | #63 merged · **user consent + key** |
| **11 · Package data (wheel install)** | [11-package-data.md](11-package-data.md) | `fix/package-data` | code + packaging | exercised (wheel in temp venv, Docker) | #63 merged · **touches `personas/`** |

**One lane at a time** in the working tree (single repo → one branch checked out at once), **unless**
lanes are made truly simultaneous via `git worktree` (the sanctioned escape hatch). Lanes that share a
hot file (`router.py`, `failure.py`, `classify()`, `reviser.py`, `personas/`, `graph.py`, `mode.py`)
can't both be in flight — one serializes after the other.

## ▶ Dispatch — what an orchestrator can start now (2026-09-29)

Each lane runs in its own `git worktree` on its own branch; start an agent with the prompt shown.
Everything else (roadmap, why) is in `TODO.md`.

| Order | Lane | Ready? | Prompt for the lane agent | Needs the user for |
|---|---|---|---|---|
| 1 | **8** — finish | ✅ now | *"continue lane 8 per `docs/lanes/08-ui-frontend.md` — do the Handover section; do not merge"* | reviewing + merging #63 |
| 2 | **10** — paid run via UI | after #63 merges | *"continue lane 10 per `docs/lanes/10-paid-run-via-ui.md`"* | **the key and the go-ahead to spend** (live-replays, then one build) |
| 2 | **11** — package data | after #63 merges | *"continue lane 11 per `docs/lanes/11-package-data.md`"* | nothing (free) |

- **10 and 11 can run in parallel** (10 only writes a findings doc). 11 moves or re-points
  `personas/`, so **no persona lane may start while 11 is in flight** — and any fix that Lane 10's
  findings call for in `personas/`/`router.py`/`failure.py` waits for 11 to land.
- **Nothing judgement-heavy should start before Lane 10's findings** (doc 22 R3/R4/R8, content-reviser
  C5, doc-18 re-run): the paid run is what tells us which of those matter.
- **Coordinator-only files:** `TODO.md` and this index. Lane agents update just their brief's
  **Status** line and hand a proposed TODO update back.
- **Worktree hygiene:** create the venv inside the worktree (`python3 -m venv .venv && .venv/bin/pip
  install -e '.[dev]'`); never run `ipykernel install --user` from a worktree (see CLAUDE.md gotchas).

**⛔ The paid artifact-lesson run is gated on a usable UI (2026-09-29).** It is the single
validation gate for judgement-heavy work, so it must exercise the product a user actually touches:
Lane 7's backend seam (✅ #59) **and** a usable UI frontend (Lane 8, PR #63) must land first — that
run is now Lane 10. Until then, keep judgement-heavy
lanes validated **offline + by live-replay for cents** — that includes running the live-replay for
Lane 6's R7 before relying on its remake behaviour. See `TODO.md`.
