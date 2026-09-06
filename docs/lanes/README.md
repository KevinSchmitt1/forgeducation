# docs/lanes — parallel workstream briefs

This directory holds the **coordination brief for each parallel lane** of the current effort. A
"lane" is an independent slice of work that runs in its own `git worktree` on its own branch, so
several agents (in several terminals) can work at once without stepping on each other.

- **How to start or resume a lane** (worktree setup, CI gates, sync): see the
  **"Parallel lane workflow"** section in the repo root `CLAUDE.md`.
- **Each lane doc** below states its goal, exact file ownership (the collision map), and its
  definition of done. Read your lane doc first, then follow it.
- **Project state / roadmap** lives in `TODO.md` (single source of truth), not here.

## Lanes

| Lane | Doc | Branch | Type | Depends on | Collision-safe in parallel |
|------|-----|--------|------|------------|----------------------------|
| 1 · Vertical-confirmation harness | [01-vertical-harness.md](01-vertical-harness.md) | `feat/vertical-confirmation-harness` | code | — | spine (owns `tests/`) |
| 2 · Local observability | [02-local-observability.md](02-local-observability.md) | `feat/local-observability` | code | — | ✅ owns `llm.py` + agents trace |
| 3 · Author-identity split | [03-author-split.md](03-author-split.md) | `docs/author-split-design` | design doc | — | ✅ doc only (impl serializes w/ R6/R7) |
| 4 · SDK-as-provider | [04-sdk-provider.md](04-sdk-provider.md) | `docs/sdk-provider-design` | design doc | — | ✅ doc only |
| 5 · UI grilling | [05-ui-exploration.md](05-ui-exploration.md) | `docs/ui-exploration` | decision doc | — | ✅ doc only |

**Held back deliberately** (not lanes yet): **R6 → R7** (need Lane 1's harness first) and the
**author-split *implementation*** (collides with R6/R7 on `personas/`, `graph.py`, `router.py`).
The **paid validation run** remains the single gate for everything downstream. See `TODO.md`.
