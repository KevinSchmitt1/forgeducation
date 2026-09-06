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
| 1 · Vertical-confirmation harness | [01-vertical-harness.md](01-vertical-harness.md) | `feat/vertical-confirmation-harness` | code (owns `tests/`) | *is* the vertical rung | — |
| 2 · Local observability | [02-local-observability.md](02-local-observability.md) | `feat/local-observability` | code | exercised + unit tests | — |
| 3 · Author-identity split | [03-author-split.md](03-author-split.md) | `docs/author-split-design` | design doc | review | — |
| 4 · SDK-as-provider | [04-sdk-provider.md](04-sdk-provider.md) | `docs/sdk-provider-design` | design doc | review | — |
| 5 · UI grilling | [05-ui-exploration.md](05-ui-exploration.md) | `docs/ui-exploration` | decision doc | review | — |

**One lane at a time** in the working tree (single repo → one branch checked out at once). Lanes that
share a hot file (`router.py`, `failure.py`, `classify()`, `personas/`, `graph.py`, `mode.py`) can't
both be in flight — one serializes after the other.

**Held back deliberately** (not lanes yet): **R6 → R7** (need Lane 1's harness first) and the
**author-split *implementation*** (collides with R6/R7 on `personas/`, `graph.py`, `router.py`). Those
implementations, and any future UI build, must reach the **vertical** rung — a real run / real browser,
not just mocked tests. The **paid validation run** remains the single gate for judgement-heavy work.
See `TODO.md`.
