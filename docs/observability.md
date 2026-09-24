# Local observability — self-hosted Langfuse

forgeducation already traces **every LLM-backed agent prompt** to Langfuse (see
`forged/llm.py`). Each generation records the resolved provider + model, token usage,
success/error — and now the **pipeline semantics** that turn a flat list of calls into a
readable reasoning loop: which stage ran, at which iteration, on which route, against the
last pass's quality score / goal-fit verdict, in which lesson mode.

This guide gets you a Langfuse UI **on localhost, no cloud account**, so those traces
have somewhere to land.

## 1. Bring up Langfuse on localhost

The stack (Langfuse web + worker, Postgres, ClickHouse, Redis, MinIO) is defined in
[`docker-compose.observability.yml`](../docker-compose.observability.yml) — a trimmed
adaptation of the upstream Langfuse v3 compose, with the cloud-only knobs removed.

```bash
docker compose -f docker-compose.observability.yml up -d
# first boot pulls images and runs migrations — give it a minute
docker compose -f docker-compose.observability.yml logs -f langfuse-web   # watch readiness
```

Open **http://localhost:3000**, create an account (stored locally), and create a project.
Everything except the web UI is bound to `127.0.0.1`, so nothing is reachable off the machine.

Tear down (keeps data in named volumes):

```bash
docker compose -f docker-compose.observability.yml down
```

To wipe all trace data too, add `-v` to remove the volumes.

## 2. Point forgeducation at it

In your project **Settings → API Keys**, create a key pair, then add them to
forgeducation's own `.env` (gitignored — never commit keys):

```dotenv
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

`forged/llm.py::_ensure_client` reads exactly these three variables. With them set, the
next run's traces appear in the UI automatically; with them absent, tracing stays silently
off and the pipeline behaves identically (observability never breaks an LLM call).

> **Skip the sign-up (optional).** The compose file exposes `LANGFUSE_INIT_*` overrides.
> Put an org/project/user with pre-chosen keys in a local `.env` **next to the compose
> file** and first boot provisions them, so you can paste the same keys straight into
> forgeducation's `.env`. No keys are committed to the compose file itself.

## 3. What a run looks like in the UI

- **One trace per run.** All of a run's generations are grouped under a single trace id
  (seeded from `pipeline_kind:run_id`), so a run reads top-to-bottom as
  `planner → code_author → executor → student → reviewer → reviser → …`.
- **Each generation carries** `stage_name`, `iteration`, `run_id`, `run_dir`, provider,
  model, token usage — plus the enriched semantics when known at call time:

  | field | meaning | known from |
  |---|---|---|
  | `route_taken` | the classification that sent the pipeline here | last routing decision |
  | `quality_score` | the latest composite the critics gave | latest student grade report |
  | `goal_fit` | "does the code earn its place?" (`fit` / `drifted` / `overwhelming` / `insufficient`) | reviewer report, else student |
  | `lesson_mode` | `executable` / `artifact` / `conceptual` | planner's `lesson-mode` block |

  Early stages omit the fields they cannot yet know (the planner's first call has no score),
  so a trace is never cluttered with null verdicts.

Filter or group by any of these in the Langfuse UI to compare, e.g., cost per stage, route
frequency across runs, or the quality trajectory across a run's iterations.

## Design notes

- **Enrichment is best-effort.** The semantics are read from pipeline state + run artifacts
  in `forged/pipeline/agents/__init__.py::_semantic_enrichment`; a missing or malformed
  artifact yields `None` for that field and never raises. This preserves the invariant that
  tracing cannot break a paid call.
- **Validated by unit tests, not paid runs.** `tests/pipeline/test_trace_enrichment.py`
  proves the enriched fields are extracted and land on the trace payload offline. The real
  localhost view is confirmed on the next paid run.
