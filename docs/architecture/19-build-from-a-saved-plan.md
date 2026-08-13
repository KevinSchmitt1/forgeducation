# 19 — Build from a saved plan (`--from-plan`)

**Status:** designed, not built (2026-08-13)
**Motivating incident:** a `--plan-only` probe produced exactly the plan the user wanted
(1 module, `mode: artifact`), and there was no way to build *that* plan. Building means
re-running the planner, which is non-deterministic, so the reviewed plan and the built
plan are not the same object.

---

## The problem

`--plan-only` exists so you can see what a build would be before paying for it. It writes
`course_plan.json` + `COURSE.md`. But nothing consumes `course_plan.json` — it is a
report, not an input. The build path always re-plans:

```
learn --plan-only  →  CurriculumPlanner.plan()  →  course_plan.json   (reviewed)
learn              →  CurriculumPlanner.plan()  →  a different plan   (built)
```

Three consequences, in increasing order of how much they cost:

1. **A reviewed plan cannot be built.** You approve a plan, then get a different one. The
   probe is advisory only.
2. **Experiments are not comparable.** Doc 18's open criteria (3 and 4) ask whether
   notebooks improved. Comparing two runs means holding the plan fixed; today every run
   re-rolls it, so plan variance and pipeline variance are confounded. `TODO.md` already
   records this under Gotchas: *"The planner's `requirements` block is LLM-non-deterministic,
   so its content hash changes between runs and the venv cache rarely hits across 'the
   same' topic."* Same root cause, wider blast radius.
3. **A crashed run cannot be resumed on the same plan.** The 2026-07-30 runs died in
   provisioning after planning. Re-running re-planned from scratch.

Evidence this matters, gathered 2026-08-13 for cents: two probes on deliberately
non-computational Copilot topics both returned `mode: artifact`; `conceptual` has still
never been observed firing across five planning calls. Investigating that is exactly the
kind of experiment that needs a fixed plan and a varying pipeline — currently impossible.

## The design

One new flag on the single front door:

```bash
forged learn --from-plan runs/probe-a-copilot-config/course_plan.json \
             --learner-profile templates/examples/kevin_learner.yaml
```

Semantics: **load the plan, skip the planner, everything downstream is unchanged.** It is
an input substitution, not a new pipeline.

### What it replaces

`_cmd_learn` currently does `planner.plan(...) → gate → _build_confirmed(...)`. With
`--from-plan` it does `load_plan(path) → gate → _build_confirmed(...)`. The gate,
provisioning preflight, orchestrator, and both engines are untouched.

### The gate still runs

Doc 16's invariant is that **nothing paid runs without confirmation**, and that holds
here. Reaching the gate is now free (no planner call), which is a strict improvement: you
can inspect and adjust a plan at zero cost before committing.

Deterministic adjustments (`merge`/`drop`/`force_single`/`reorder`, and `set_mode` from
doc 18) operate on the loaded `CourseSpec` and keep working unchanged. Only the guided
re-plan escalation needs the planner — it stays available, and using it simply means you
are no longer building the saved plan. That should be stated in the gate output.

## What has to be written

### 1. `course_from_dict` — the missing inverse

`forged/curriculum/model.py:139` has `course_to_dict`. **There is no deserializer.** This
is the bulk of the work, and it is a system boundary, so it validates rather than trusts:

- reject unknown/missing keys with an actionable message naming the file and the field;
- rebuild `TopicSpecification` (`title`, `scope`, `learning_objectives`, `prerequisites`,
  `constraints`, `depth`, `focus_areas`) and `ModuleSpec` (`spec`, `order`,
  `module_prerequisites`, `remediation_for`, `lesson_mode`);
- restore tuples, not lists — `ModuleSpec`/`CourseSpec` are frozen and prefer tuples;
- validate `lesson_mode` against the three known modes, and `order` for contiguity from 0;
- round-trip property: `course_from_dict(course_to_dict(c)) == c`.

### 2. A `version` field in the payload

`course_plan.json` currently has no schema version. Add one at write time and refuse a
payload whose version is newer than the running code. Without it, a plan saved today and
loaded after a `ModuleSpec` field change fails somewhere deep instead of at the boundary.

### 3. Persist the topic alongside the plan (additive)

The payload holds `{"course": ..., "fidelity": ...}` — no raw topic string. Downstream
needs one: `topic_spec` drives the fidelity detector, and `_build_confirmed` takes
`topic`. Options considered:

| Option | Verdict |
|---|---|
| Require `--topic` next to `--from-plan` | Rejected — retyping the topic invites drift from the one the plan was made for, silently invalidating the fidelity check |
| Store `topic` + `topic_spec` in the payload | **Chosen** — additive, backwards-compatible, keeps the plan self-describing |
| Store the learner profile too | Rejected — the profile is *who is learning*, not *what is taught*; keeping it a separate flag lets one plan serve different learners, which the course hand-down already assumes |

`--topic` alongside `--from-plan` then means "override", and should warn when it differs
from the stored one rather than silently re-deriving capabilities.

## What this deliberately does not do

- **No resume-mid-run.** Restarting a partially built course (skip completed modules) is a
  bigger feature touching `CourseResult` and run-dir layout. Out of scope; `--from-plan`
  only removes the planning non-determinism.
- **No plan editing by hand as a supported path.** Hand-edited JSON is accepted if it
  validates, but the supported flow is probe → review → build.
- **No caching/dedup of plans.** YAGNI until there is a reason.

## Test plan

Unit, all offline:

- round-trip `course_from_dict(course_to_dict(c)) == c`, including `lesson_mode`,
  `remediation_for` and `module_prerequisites`;
- each malformed payload (missing key, unknown mode, non-contiguous order, future
  version) fails with a message naming the file and field, and exits `EXIT_USAGE`;
- `--from-plan` never constructs a `CurriculumPlanner` — assert it, since the whole point
  is skipping a paid call (the `conftest` guard from PR #37 already makes an accidental
  live call fail loudly);
- the gate receives the loaded course verbatim, and a `set_mode` adjustment still applies;
- `--from-plan` with a nonexistent path is a usage error, not a traceback.

Entry-point smoke (`tests/test_entrypoint_smoke.py`): `--from-plan` on a missing file
exits 2 with no traceback.

## Cost and value

It saves one `gpt-5-mini` planner call per run — negligible in money. **The value is
reproducibility, not cost:** a plan you reviewed is the plan you build, and an experiment
can hold the plan fixed while varying the pipeline. That is a precondition for closing
doc 18's criteria 3 and 4, and for investigating why `conceptual` never fires.

## Open questions

1. Should `--from-plan` imply `--yes`? **Recommendation: no.** The plan may have been
   saved days earlier against a different code version; a free confirmation is cheap
   insurance, and doc 16's invariant is that spending is always confirmed.
2. Should `COURSE.md` (human-readable) also be loadable? **No** — one machine-readable
   input is enough; two parsers for one concept is the mistake this doc's sibling fix
   (PR #38, three renderers for one plan) just undid.
