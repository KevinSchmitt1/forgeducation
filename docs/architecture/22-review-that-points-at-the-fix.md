# 22 — A review that points at the fix

**Status:** designed, not built (2026-08-16)
**Evidence:** `runs/20260813-201647_create_and_validate__github_co/` (docs 20, 21)
**Follows:** C5 (patching) landed the *mechanism* for targeted repair. This doc is about the
*signal* that drives it — which is currently not targeted at all.

---

## The complaint

Two observations from review, both of which the run data supports:

> *"The reviewer agreed on stuff he did not review badly."*
> *"The review is not pointing directly to stuff which needs to get fixed."*

And two requirements added to the design:

> *"Does the code fulfill the goal of the lesson? Is this code needed for the learner to
> learn the topic? Is it not overwhelming but educationally sufficient?"*
> *"Iterations should focus on correcting the bad or insufficient stuff… nevertheless there
> should be a threshold which makes it possible to remake everything BUT with the premise to
> use the feedback of the reviewers to produce a much better notebook."*

## Part I — Five defects the run exposes

### D1. The rubric averages a fatal condition into a passing mark

Quality across the four iterations: **74 → 82 → 74 → 71**, on notebooks where **nothing ever
ran to completion**. Iteration v1 scored the *highest* mark of the run — 82/100 — while
producing zero artifacts.

`RubricScores.composite()` is the equal-weighted mean of five dimensions, so v2's
`structure 85, explanation_depth 80, code_clarity 75, correctness 50, learner_fit 80` averages
to 74. A notebook that does not execute cannot be a B-grade lesson, but the arithmetic has no
way to say so: four healthy dimensions outvote the one that is fatal.

### D2. The critics spend their budget re-reporting the execution report

v2's five findings were three BLOCKERs restating "cells 12, 17, 20 failed", one MEDIUM about
`\n` rendering, one LOW. The executor already knows which cells failed — deterministically,
for free, before any grader runs. Three of five findings carried no information we did not
already have, paid for at grader rates.

### D3. Severity is uncalibrated against consequence

The self-referential validator bug — the document forbids hardcoded secrets, names `PASSWORD`
doing so, and the generated validator flags any `PASSWORD` as a leak, so the artifact fails
the check it describes — was filed **LOW**, phrased as a style preference about
case-sensitivity. It is one of the only two root causes still failing the notebook after C5's
patch (doc 21). Correctly spotted, ranked last, never acted on.

### D4. Findings do not name what to change

A finding today is severity + cell index + prose. What the author needs, especially now that
it can patch, is *which cell to change and what the changed cell must satisfy*. A finding that
names a target is a patch entry waiting to happen; a finding that describes a feeling is not.

### D5. Feedback does not accumulate — and a rewrite discards all of it

Every agent reads exactly `revision_brief_v{iteration - 1}` — verified across
`code_author.py`, `planner.py`, `content_reviser.py`. **No agent ever sees more than one
brief.** Each iteration's critique supersedes the last.

So when iteration 3 rewrote the notebook, it did so knowing nothing of what iterations 0–2
revealed. This is the mechanism behind quality *declining* after v1: each rewrite is a fresh
roll, not a cumulative improvement. It is also exactly the failure the second requirement
above names — a remake must be *informed*, or it is just another attempt.

## Part II — The question the review does not ask

The rubric measures structure, explanation depth, code clarity, correctness and learner fit.
Every one of them is about *how well the code that exists is presented*. None asks whether
that code should exist.

The founding complaint of this project (doc 18) was that lessons came out **code-heavy and not
practical** — too much machinery, insufficiently tied to the goal. Nothing in the review can
express that, so nothing catches it.

### D6 — add a dimension: does this code earn its place?

Three questions, judged against the lesson's stated objective and its mode:

1. **Goal fit.** Does this code serve the objective the plan named, or has the lesson drifted
   into adjacent machinery that merely runs?
2. **Necessity.** Is every block something the learner needs in order to reach that goal?
   Scaffolding they will never touch again, defensive branches, elaborate helper classes, and
   configuration knobs the lesson never varies are all *cost* to a learner, not value.
3. **Sufficiency.** Is what remains enough to actually learn the thing — or has it been
   trimmed past the point of teaching?

Necessity and sufficiency are one axis with two failure directions, which is why they belong
in a single dimension rather than two: a lesson can be overwhelming *and* insufficient at once
(the 2026-08-13 run was), and a grader forced to pick a direction will say "fine".

This dimension must be **mode-aware**, like the anti-hollow gate: for `artifact` lessons the
question is whether the artifact is one the learner would keep and could reproduce, not
whether a computation was impressive.

## Part III — Repair by default, remake by decision

C5 made targeted repair *possible*. This part makes it the default, and defines the escape.

### The default: repair what is bad or insufficient

The brief drives a patch. Findings name targets (D4). Untouched cells stay untouched — which
also protects good explanations the earlier round produced, another way v3 was worse than v1.

### The threshold: when a remake is the right answer

A remake is correct when the *shape* is wrong rather than the cells: the plan was misread, the
lesson teaches the wrong subject, most cells would be patched anyway, or repeated patches have
not reduced the failures (the C6 signal from doc 21).

The trigger should be a **judgement the reviser makes from evidence it already has** — failure
counts, quality trend, share of cells implicated — not a magic number in code. What must be
deterministic is that the decision is *recorded*, so a remake never happens silently.

### The premise: a remake must be informed, or it is a re-roll

This is the part D5 blocks today, and it is the requirement that matters most.

A remake must receive an **accumulated critique** — every finding from every iteration,
deduplicated and ordered by consequence, not just the last brief. "Write it again, better,
knowing everything four critics have said" is a different instruction from "write it again",
and today only the second is possible.

Concretely: a `critique_digest` artifact the reviser maintains across iterations, appended to
rather than replaced. It costs nothing to produce — the findings already exist — and it is the
only thing that makes a rewrite an improvement rather than another sample.

## Part IV — What changes where

| # | Change | Where | Kind |
|---|---|---|---|
| R1 | A fatal condition gates the verdict instead of averaging into it | `failure.py` classify/rubric | code |
| R2 | Critics stop re-reporting execution failures; the brief carries them once | `student.md`, `reviewer.md` | persona |
| R3 | Findings name a target cell and what it must satisfy | grader JSON schema + personas | code + persona |
| R4 | Severity is calibrated to consequence, with the `PASSWORD` case as the worked example | `student.md`, `reviewer.md` | persona |
| R5 | New rubric dimension for goal fit / necessity / sufficiency, mode-aware | `failure.py` + all grader personas | code + persona |
| R6 | `critique_digest` accumulates findings across iterations | `reviser.py` | code |
| R7 | Remake is a recorded decision, informed by the digest | `reviser.py`, `code_author.md` | code + persona |
| R8 | C6 non-convergence signal ("look for a systematic cause") | `reviser.py` brief text | code |

## Part V — Sequencing

**R1 and R2 first.** Both are small, and either alone would have changed the outcome of the
2026-08-13 run: R1 stops an 82/100 being awarded to a notebook that produced nothing, and R2
frees the critics' entire budget for judgement instead of restating the execution report.

**R5 next**, because it is the one that addresses the founding complaint, and because it is
worthless without R1 — a new dimension averaged into a mean that already hides fatal
conditions changes nothing.

**R6 then R7**, in that order: the digest must exist before a remake can be informed by it.

**R3, R4, R8 last** — R3 is the most valuable for patch quality but depends on the schema
change landing cleanly, and R4/R8 are calibration once the structure is right.

## Part VI — How this gets validated without spending

The corpus supports more than unit tests:

- **R1**: re-score the four real `student_grade_report_v*.json` payloads under the new gating.
  v1 (82/100, zero artifacts) must come out not-acceptable. If it does not, R1 is wrong.
- **R5**: the real notebooks are the test set. A dimension that cannot distinguish v3's 26-cell
  sprawl from a lesson that teaches the same thing in 12 is not measuring what it claims.
- **R6**: rebuild the digest from the four existing briefs and check the `PASSWORD` finding
  survives to the top rather than being lost with its iteration.

Only R7's remake behaviour needs a live run, and only after the rest.

## Part VII — Open questions

1. **Does R5 belong in the rubric or beside it?** Adding a sixth dimension changes every
   grade's arithmetic and makes historical scores incomparable. The alternative is a separate
   verdict the classifier reads directly. Leaning toward a separate verdict for exactly the
   reason D1 exists — averaging is what hid the problem in the first place.
2. **Should the Student and the Reviewer answer D6 differently?** The Student is the learner
   POV ("was this too much for me?"), the Reviewer is the expert ("was this the right
   material?"). Probably yes, and probably that is the point.
3. **Does `content_reviser` need C5's change too?** It rewrites prose on the `CONTENT_QUALITY`
   route and has the same never-sees-its-own-output shape. Almost certainly yes; deferred so
   that C5 is validated by one run before the pattern is copied.
