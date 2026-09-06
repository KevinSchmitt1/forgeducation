# Lane 5 — UI grilling session (DECISION DOC)

**Branch:** `docs/ui-exploration` · **Type:** interactive discussion → decision doc, no code
**Depends on:** none · **Status:** not started
**Process:** see "Lane workflow" in root `CLAUDE.md`. Read `README.md` first.

> **Note:** this lane *decides whether/what UI to build* → the deliverable is a doc (validated by
> review). The eventual **UI build is a separate future lane** and must be verified vertically in a
> real browser (e2e / Playwright) — a UI is the most vertical-hungry deliverable, not the least.

## Purpose
Kevin wants a **"grilling session" about building a UI** for forgeducation. The job is NOT to jump to
building — it's to interrogate the idea hard, surface the real options and tradeoffs, and end with a
captured decision. Push back; don't rubber-stamp.

## Ground truth
- Today forgeducation is a **CLI**: `forged learn --topic "…"`. One command. Plans first, pauses at an
  **interactive plan-confirmation gate** before anything paid runs, then runs a multi-agent LangGraph
  pipeline and writes a runnable, self-checked notebook to `runs/`.
- **Lane 2 is building local observability** (self-hosted Langfuse dashboard on localhost). **Do not
  design a second dashboard** — run-observation UI likely belongs there. Coordinate, don't duplicate.

## Grill these (drive the session)
- **Who is the UI for, and which moment does it improve?** The plan-confirmation gate? Browsing/reading
  generated notebooks? Kicking off runs? Watching a run live (overlaps Lane 2)? Managing a course?
- **What does a UI unlock that the CLI genuinely can't** — or is this polish over substance while the
  core quality loop (R6/R7, paid-run validation) is unfinished?
- **Build vs buy vs none**: Jupyter/nbviewer for the artifact? A thin local web app? A TUI? Nothing yet?
- **Cost of ownership**: a second surface to keep in sync with a fast-moving pipeline.

## Deliverable
`docs/architecture/25-ui-exploration.md` (next number after 24) — options, tradeoffs, and a
**recommendation or explicit decision** (including "not now, because …" with the trigger that would
revive it).

## Done means
A decision doc a future implementer could act on — or a reasoned defer. Open a PR.
