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
| **8 · UI frontend v1 (BYOK front door)** | [08-ui-frontend.md](08-ui-frontend.md) | `feat/ui-frontend` | code, additive | real browser (Playwright, stubbed LLM) | Lane 7 ✅ · **critical path — gates the paid run** |
| **9 · Author-split implementation** | [09-author-split-impl.md](09-author-split-impl.md) | `feat/author-split` | code + persona | offline + exercised (live-replay owed) | doc 23 ✅, Lane 6 ✅ · **hot-file lane** |

**One lane at a time** in the working tree (single repo → one branch checked out at once), **unless**
lanes are made truly simultaneous via `git worktree` (the sanctioned escape hatch). Lanes that share a
hot file (`router.py`, `failure.py`, `classify()`, `reviser.py`, `personas/`, `graph.py`, `mode.py`)
can't both be in flight — one serializes after the other.

**Active pair (2026-09-29):** Lane 8 (UI frontend) is on the critical path — the paid run waits
for it. Lane 9 (author-split implementation, doc 23 option B) owns `personas/` + the author agent;
Lane 8 owns `cli.py`, `forged/service.py`, `forged/ui/`, `pyproject.toml`, `Dockerfile`. Disjoint →
they run in parallel via `git worktree`. While both are in flight, **only the coordinator edits
`TODO.md` and this index**; lanes update just their own brief's Status line.

**⛔ The paid artifact-lesson run is gated on a usable UI (2026-09-29).** It is the single
validation gate for judgement-heavy work, so it must exercise the product a user actually touches:
Lane 7's backend seam (✅ #59) **and** a usable UI frontend (Lane 8) must land first. Until then, keep judgement-heavy
lanes validated **offline + by live-replay for cents** — that includes running the live-replay for
Lane 6's R7 before relying on its remake behaviour. See `TODO.md`.
