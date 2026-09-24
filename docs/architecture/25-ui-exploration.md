# 25 — A UI for forgeducation: the grilling, and the decision

**Status:** DECIDED 2026-09-24 · **verdict: BUILD, scoped** — a local, self-hostable
(Docker), **bring-your-own-key** web front door that composes the run inputs, lets the user
edit the plan at the cost gate, and launches the run. Live-run observation and notebook
reading are **explicitly out of scope** (owned by Lane 2 and by Jupyter). Priority: a
parallel track that ranks **below** the paid-run + R6/R7 validation (TODO's binding
constraint), because it does not compete for the hot pipeline files — only for attention.
**Lane:** `docs/lanes/05-ui-exploration.md` (decision doc). **The build is a separate future
lane** and must be verified in a real browser (e2e / Playwright).

---

## What this lane was asked to do

Not "build a UI" — **grill the idea** hard, surface the real options and tradeoffs, and end
with a captured decision (`docs/lanes/05-ui-exploration.md`). Push back; don't rubber-stamp.
This doc records the grilling and the decision it produced. It is a design snapshot, not a
build.

## Ground truth going in

- forgeducation is a **one-command CLI**: `forged learn --topic "…"`. It plans first, pauses
  at an **interactive plan-confirmation gate** before anything paid runs, then runs a
  multi-agent LangGraph pipeline that **executes** the generated notebook and writes a
  runnable, self-checked lesson/course to `runs/`.
- **The core quality loop is not yet validated by a single paid run.** TODO says it in bold,
  twice: *"the next paid artifact-lesson run is the binding constraint on almost every open
  question… and it is worth more than the next feature."* R6/R7 (the critique digest) are not
  built. Any UI decision has to survive that fact.
- **Lane 2 is building local observability** (self-hosted Langfuse on localhost). Watching a
  run live belongs there. **Do not design a second dashboard.**

---

## The grilling

Five candidate "moments" a UI could improve, each with a different verdict:

| Moment | Verdict | Why |
|---|---|---|
| Reading the generated notebooks | **Reject** | Jupyter / nbviewer already render notebooks well. A bespoke reader competes with mature tools and earns nothing. |
| Watching a run live | **Reject (out of scope)** | This is Lane 2's territory (self-hosted Langfuse). Building it here duplicates a surface already in flight. |
| Kicking off a run (a form for `--topic`) *alone* | **Weak** | The CLI flag is already trivial; a one-field form is not a reason to stand up a web stack. |
| The plan-confirmation gate | **Strong (paired)** | The one moment that gates real money — visualizing the module DAG, modes, and cost, and editing the plan before spending, is genuine value. But only worth a UI if paired with input authoring. |
| **Composing the inputs** | **Strong — the real target** | See below. |

### The objection I opened with, and where it landed

*Opening position:* "A UI now is polish over substance, and worse, a second surface to keep in
sync with a pipeline still changing weekly — the paid run outranks it."

**This objection holds for a run dashboard. It does not hold for an input front door**, and
that distinction is the whole finding. The reason is the schema:

- The inputs a UI would author — `LearnerProfile` (7 fields) and `TopicSpecification`
  (5 fields) in `forged/models.py` — are among the **most stable** parts of the codebase.
  They barely change, unlike the pipeline internals a run-observation UI would have to track.
- Composing them today means **hand-editing YAML and knowing the enum vocabulary by heart**:
  `material_density` accepts exactly `dense | standard | rich`; `learning_style` exactly
  `socratic | project_based | visual | hands_on | reference`; `environment` one of six;
  `scope` one of four. Type `"medium"` and it fails at load. Three enums + three
  list-of-strings + free text across ~15 fields is **real, error-prone friction** that a form
  with typed controls eliminates outright.

So the UI that survives the grilling is the one Kevin actually asked for: **a front door for
composing inputs**, extended through the plan/cost gate. It targets the surface *least*
exposed to churn and *most* burdened by hand-YAML — the inverse of the surface the opening
objection was about.

---

## What was decided (the two pivotal forks)

Two questions decided the shape. Both were answered by Kevin during the session.

### Fork 1 — who runs it: "accessible for anyone," **bring-your-own-key**, self-hosted

Kevin: *"it should be accessible for anyone… a prerequisite is that someone can input his API
key / subscription / SDK, which then gets used in the software. I do not want my API key used
by everyone. Maybe a Docker solution in the long term."*

This answer **collapses the scariest version of "anyone can use it."** The nightmare is a
multi-tenant service Kevin operates: auth, quotas, custody of other people's secrets, and
— worst — **executing strangers' generated code on his server** (the pipeline runs generated
code in a kernel by design; that is remote-code-execution-as-a-feature). Bring-your-own-key
(BYOK) + self-hosting via Docker dissolves all four:

| Risk of "anyone can use it" | Neutralized by |
|---|---|
| Strangers spend Kevin's tokens | **BYOK** — each user supplies their own key; the cost is theirs |
| Kevin holds other people's API keys | **Self-host** — the key never leaves the user's own container |
| Multi-tenant auth / quotas / ops | **Self-host** — one tenant per instance; no shared service to run |
| Executing untrusted generated code on a shared box | **Docker** — the container *is* the execution sandbox, per user, on their machine |

**Therefore Docker is not "long term" — it is v1.** It does triple duty: distribution
("accessible for anyone" = `docker run`, no Python setup), per-user isolation, and the
code-execution sandbox the pipeline needs anyway. Designing for it later means retrofitting
the security model; designing for it now is free because the app is single-tenant from day one.

**Decision:** a **local, single-tenant, self-hostable web app, distributed as a Docker
image, bring-your-own-key.** Not a service Kevin operates.

### Fork 2 — how far into the run: inputs + **plan-gate edits** + kickoff (not live streaming)

Kevin chose: **inputs + plan/cost preview + own the plan-gate edits + kickoff.** The UI:

1. authors valid `LearnerProfile` / `TopicSpecification` via typed controls (dropdowns for the
   enums, add/remove rows for the lists) — no hand-YAML, no invalid-enum errors;
2. runs `plan()` (cheap) and shows the module DAG, per-module **lesson mode**, and the cost
   estimate — the gate, made visual;
3. lets the user **edit the plan before spending** (merge / drop / reorder modules, override a
   mode, or trigger a guided re-plan) — the existing `PlanAdjuster` round-trip, in-UI;
4. confirms and **launches** `build(confirmed_plan)`.

**Out of scope, by decision:** live-run streaming (→ Lane 2 / Langfuse) and notebook reading
(→ Jupyter). The UI's job ends when the run is launched; how the run is *watched* and the
output *read* are owned elsewhere. This keeps the lane bounded and non-duplicative.

---

## Why the backend is more ready than it looks (the load-bearing finding)

The expensive part of "own the plan-gate edits" sounds like it needs a pipeline rewrite. It
does not. The current gate is already **plan-as-data and stream-injected**, so the seam a UI
needs mostly exists:

- **`plan()` and `build(course)` are already separable phases.** `forged learn --plan-only`
  produces and checks the plan with no build cost; `_build_confirmed(…, course=…)` takes a
  `CourseSpec` object and runs it. The two-phase boundary the UI wants is already how the CLI
  is structured (`forged/cli.py`).
- **The gate is already parameterized on its I/O.** `run_gate(...)` in `forged/curriculum/`
  takes `input_stream` / `output_stream` rather than calling `input()` directly — so it is not
  hard-wired to a terminal.
- **Plan edits are already deterministic ops on plan data.** `PlanAdjuster`
  (`forged/curriculum/adjuster.py`) classifies an instruction into `merge / drop /
  force_single / reorder / confirm / cancel`, with a gpt-5-mini re-plan as the only
  escalation. That is exactly the step-function a UI calls per edit.

**What is actually missing is small and already tracked:**

1. **`course_from_dict`** — the inverse of `course_to_dict` (`forged/curriculum/model.py`
   has `course_to_dict`; the inverse does not exist). Needed so a plan can round-trip UI ↔
   backend as JSON. **Doc 19 already identified this exact gap** ("the missing piece is
   `course_from_dict`").
2. **Expose the gate as a step function**, not a stdin loop — i.e. `apply_adjustment(course,
   instruction) → new_course` as a callable, which the deterministic ops in `adjuster.py`
   already implement underneath; the loop in `run_gate` just needs to not own the I/O.

Both are **additive** and touch only `forged/curriculum/model.py` + a thin service wrapper —
**not** `router.py`, `failure.py`, `classify()`, `personas/`, `mode.py`, or `graph.py`. So a
UI lane is **parallel-safe** with the quality-loop work; it does not contend for the hot files.

The implication for the estimate: **the frontend is the bulk of the work; the backend surgery
is a few days and de-risks other surfaces too** (any future automation wants the same
two-phase library API).

---

## Tech-stack recommendation

The v1 scope is *forms + a stateful plan-edit loop + a launch button + a BYOK settings field*,
shipped as a Docker image for a Python codebase that prizes KISS / YAGNI.

**Recommendation: build v1 in a Python-native app framework (Gradio or Streamlit).**

| | Gradio / Streamlit (recommended v1) | FastAPI + JS frontend (React/Svelte) |
|---|---|---|
| Fit for forms + enums + list rows | Native, minimal code | Full control, more code |
| Stateful plan-edit loop | `session_state` handles it | Native, more plumbing |
| BYOK secret field | Trivial (in-memory) | Trivial |
| Docker | One small image | Two build steps |
| New dependency surface | Small, Python-only | Large (JS toolchain) |
| Churn exposure | Low | Higher |
| Ceiling (live-run views, polish) | **Hits a wall** | No wall |

Gradio/Streamlit is the fastest path to a real, Dockerable, BYOK front door and — importantly
— it **proves the two-phase library API** with the least ceremony. It respects the repo's
YAGNI ethos: build the smallest thing that delivers the decided scope.

**Graduation trigger to FastAPI + a real frontend:** the moment the UI needs to *own live-run
views* (which today is Lane 2's job) or needs design polish beyond what the Python frameworks
give. Until then, that heavier stack is speculative generality. Record the trigger; don't
pre-build for it.

---

## Scope — in and out

**In (v1):**
- Typed input authoring for `LearnerProfile` + `TopicSpecification` (dropdowns for enums,
  add/remove rows for lists), producing validated objects — no hand-YAML.
- BYOK: a settings field for the user's API key / provider credential, held in memory for the
  process, **never written to disk, never logged, never in a trace payload.**
- Plan/cost preview: run `plan()`, render the module DAG + per-module lesson mode + cost
  estimate.
- In-UI plan edits via the existing `PlanAdjuster` ops + guided re-plan.
- Launch `build(confirmed_plan)`.
- Shipped as a **Docker image** (`docker run` → localhost app), single-tenant.

**Out (by decision):**
- Live-run streaming / agent-progress dashboard → **Lane 2** (self-hosted Langfuse).
- Notebook reading/rendering → **Jupyter / nbviewer.**
- Multi-tenant hosting, auth, quotas, Kevin-operated service → **not built; BYOK + self-host
  is the deliberate alternative.**
- A bespoke JS frontend → deferred behind the graduation trigger above.

---

## Priority and sequencing

**This is greenlit as a parallel lane, ranked below the paid-run + R6/R7 validation.** It does
not compete for the hot pipeline files (its backend additions are additive and confined to
`model.py` + a service wrapper), so it *can* proceed alongside the quality-loop work. But
attention is finite, and TODO's binding constraint is unchanged: **the next paid
artifact-lesson run is worth more than the next feature.** So the sequencing rule is:

- The UI **must not** delay or consume the budget for the paid run or R6/R7.
- Its **first deliverable is the backend seam** (`course_from_dict` + gate-as-step-function),
  because that is cheap, additive, and de-risks the whole idea — and is independently useful.
- The frontend follows once the seam is proven with a thin spike.

**Revive/kill triggers:**
- **Revive to active build** when the paid run has validated the quality loop *or* when the
  backend seam is wanted for another reason (automation, a second entry point). Either
  unblocks the UI without it having stolen focus.
- **Kill / reduce to nothing** if the paid run reveals the pipeline's shape must change
  substantially (e.g. the plan/build phase boundary moves) — the UI's premise is that the
  two-phase seam is stable; if it isn't, the UI waits.

---

## First-implementer plan (for the future build lane)

1. **Backend seam (a few days, additive, parallel-safe):** add `course_from_dict` (inverse of
   `course_to_dict`) with a round-trip test; extract `apply_adjustment(course, instruction) →
   course` from `run_gate` so the gate logic is callable without stdin. No changes to
   `router.py` / `failure.py` / `personas/` / `graph.py` / `mode.py`.
2. **Thin service layer:** `plan(inputs) → CourseSpec-as-dict`, `apply_adjustment(plan,
   instruction) → plan`, `build(plan, inputs) → run_dir`. BYOK key injected per-request into
   the provider client (`forged/llm.py` already reads the key from env; the service sets it
   for the process, never persists it).
3. **v1 app (Gradio/Streamlit):** input forms → plan preview → edit loop → launch. Verify in a
   **real browser (Playwright)** — a UI is the most vertical-hungry deliverable, per the lane
   workflow.
4. **Dockerfile:** single-tenant image; document `docker run` + where to paste the key. The
   container is both the distribution unit and the code-execution sandbox.

---

## Open questions for the build lane (not blocking this decision)

- **Where does `build()` execute relative to the UI process?** In-container subprocess (simple,
  single-tenant) vs a job/queue (needed only if one instance ever serves concurrent runs —
  YAGNI for single-tenant). Default to subprocess; revisit only if concurrency appears.
- **Provider abstraction for BYOK.** Today the key is an OpenAI key read from env. "Subscription
  / SDK / whatever" implies more than one provider path; that intersects the SDK-as-provider
  design lane (`docs/lanes/04-sdk-provider-design.md`). Coordinate — do not design a second
  provider layer here.
- **Mid-run gate for a course vs a single lesson.** The single-lesson path has no course-level
  fidelity gate; the course path does (`assess_course_fidelity`). The UI must render both
  cases; confirm the plan preview covers the 1-module and N-module shapes.
