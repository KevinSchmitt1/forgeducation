# 12 — Learner Orientation Cell ("Start Here")

**Status:** ✅ IMPLEMENTED (2026-06-24). Persona-only change (Planner + Code Author), validated by
`tests/pipeline/test_orientation_persona.py` (6 real-persona contract tests). Phase 3 (deterministic
backstop) remains deferred under YAGNI. Full suite green (416 passed); CI gates pass
(`ruff`, `mypy`, coverage 92.4% ≥ 80%). Design of record; not yet implemented. Origin: a real
learner (the profile this pipeline targets) opened the accepted `lesson_notebook_v3` from the
`localLLM-r1-validate` run and reported *"I don't even know what's happening — I never worked with
torch."* The notebook executed cleanly and scored 81, yet still failed this learner at the very first
hurdle: it never told them, in plain language, **what the lesson is**, **what it assumes**, and
**which assumed thing they most likely lack**.

This is a **learner-fit** defect, not a correctness one — and it is adjacent to R1
(`11-topic-fidelity-r1.md`): R1 makes the pipeline honest about *what it teaches*; this makes it
honest about *what it expects the learner to already know*.

---

## Hand-off — read this first

### The symptom (observed, not hypothetical)
On topic *"setup and train local LLMs on Apple Silicon M1"*, `lesson_notebook_v3` opens with an
overview cell that already exists (Code Author `output format` rule: "start with a markdown
title/overview cell"). Its actual content:

> Setup and fine-tune a small LLM on Apple Silicon (M1) with MPS + LoRA
> You'll set up a local PyTorch + Hugging Face stack… confirm the Metal (MPS) backend… fine-tune a
> lightweight causal LLM (distilgpt2) with parameter-efficient LoRA adapters. We'll: …

That is a competent **"what you'll do" roadmap** — but it is written entirely in the topic's own
vocabulary (*MPS backend, LoRA adapters, causal LLM*). For a learner who has never seen PyTorch,
those terms **are the confusion**, so the orientation orients nothing. It also never states what the
lesson **assumes the learner already knows**, nor flags the one prerequisite they are most likely
missing.

### The information already exists — it just never reaches the learner
The Planner (`personas/planner.md`) already computes, every run, in `## Required background & gaps`:

- a per-concept `KNOWN` / `GAP` tagging against the learner's profile, and
- an explicit **"Must teach from scratch"** list of the gaps.

On this exact run the plan (`lesson_plan_v0.md`) tagged *"what a tensor is / basic PyTorch model
anatomy"* and *"pretraining vs fine-tuning / LoRA"* as **GAP**, and *"prompt engineering / CLI"* as
**KNOWN**. That is precisely the orientation the learner needed — *"this assumes PyTorch basics you
don't have yet; the training-loop primer is the keystone, slow down there."* But the gap analysis
**dies in the plan file**. The Code Author consumes it only to scaffold each gap *inline before its
code* (rule 5); it is never surfaced **up front, as data, in the learner's vocabulary**.

### Root cause (one sentence)
The Planner produces a learner-calibrated prerequisite map; nothing in the pipeline turns it into a
**learner-facing orientation**. The existing overview cell is a *topic* summary, not a *learner*
orientation.

---

## Part I — Design decisions

1. **Surface existing analysis; do not compute anything new.** The Planner already produces the
   `KNOWN`/`GAP` map and the goal. The feature is an **information-routing** change — render that map
   into the notebook — not a new analysis stage or LLM call in the loop core. This keeps cost flat.

2. **The orientation cell is a distinct *altitude*, not a second overview.** It is the 30,000-ft
   "what is this, what do you need, where's the hard part" — explicitly **not** a re-explanation of
   each concept (that already happens inline per Code Author rule 5 / "Explanation cells"). The
   guard against redundancy is altitude discipline, enforced in the persona and checkable by the
   Reviewer critic.

3. **Plain language beneath the jargon is mandatory.** The orientation must state the goal once in
   pre-jargon terms ("teach a small existing AI model a new behavior by showing it examples, on your
   Mac") *before* introducing the named technologies. Jargon-only orientation is the observed failure
   mode.

4. **A plain-language roadmap is a required element, with two facets.** Beyond the one-line goal, the
   orientation carries a short **plain-English roadmap** that **leads with everyday language**. It need
   not hard-cut the real vocabulary: where a topic term is unavoidable, give the plain phrase first and
   put the real term in **parentheses** ("a quick warm-up that shows the one move all of this repeats
   (a *training step*)"). The rule is *plain-first, jargon-in-brackets* — never a bare acronym standing
   alone as if the learner already knows it. It answers two questions a lost learner actually has:
   - **What the notebook does** — the path, beat by beat, in everyday language ("first we check your
     computer can do the work; then a tiny warm-up shows the one move all of this repeats (a *training
     step*); then we borrow a ready-made model and nudge it with a handful of examples (*fine-tuning*);
     then we check it changed").
   - **What you should be able to understand afterward** — the takeaways as plain capabilities ("you
     should be able to explain what training actually does to a model, and why we adjust only a small
     part of it (*LoRA*) instead of the whole thing").
   The real terms are introduced in brackets here and explained in full *later*, inline, so the learner
   meets each term already knowing what role it plays. This is the element the observed failure most
   directly lacked.

5. **"Where fitting" is gated by the gap analysis, not a new heuristic.** If the Planner's
   `GAP` list is empty (the learner already has every prerequisite) and the topic is shallow, the
   orientation collapses to a one-line framing or is skipped. The gate reuses data the Planner
   already emits — no separate "does this notebook need orientation?" judgment.

6. **Persona-level, mirroring R1.** Like R1's primary fix, this is a persona change (Planner +
   Code Author), not pipeline-graph code. It rides the existing `planner → code_author` flow.

---

## Part II — Patterns to mirror

| Concern | Source | Pattern |
|---|---|---|
| Gap analysis already computed | [personas/planner.md `## Required background & gaps`](../../personas/planner.md#L41-L60) | `KNOWN`/`GAP` tagging + "Must teach from scratch" list — the data this feature surfaces |
| Author already opens with an overview | [personas/code_author.md output format](../../personas/code_author.md#L88-L100) | refine the existing first cell instead of adding a competing one |
| Inline gap scaffolding (do not duplicate) | [personas/code_author.md rule 5](../../personas/code_author.md#L41-L53) | per-concept teaching stays inline; orientation stays at survey altitude |
| Density calibration | [personas/code_author.md "Calibrate depth"](../../personas/code_author.md#L83-L86) | orientation length scales with `material_density`, same as concept cells |
| Honesty-by-surfacing, learner-facing | [11-topic-fidelity-r1.md](./11-topic-fidelity-r1.md) | R1 surfaces *dropped capabilities*; this surfaces *assumed prerequisites* — same "make the hidden thing visible" principle |

---

## Part III — Phased implementation plan

Each phase is TDD (RED → GREEN → refactor) and must leave the suite green. CI gates
(`ruff`, `mypy`, `pytest --cov-fail-under=80`) run before any phase is called done.

### Phase 1 — Planner emits an explicit orientation beat (persona-only)
The Planner already has all the inputs; it just needs to designate the orientation explicitly so the
Author has an unambiguous contract.

- Edit `personas/planner.md`: add a short instruction that the plan must make the **learner-facing
  orientation** an explicit deliverable — a one-line plain-language goal, plus a "you'll need to
  already understand X; the gap you're most likely missing is Y" line derived from the existing
  `KNOWN`/`GAP` map. State the **gate**: if there are no `GAP`s and the topic is shallow, the
  orientation is a single framing line (or omitted), never filler.
- No new output section required if it can ride `## Required background & gaps`; prefer reusing it.
- Test: planner prompt assembly / persona contains the orientation-beat + gate instruction
  (mirror `test_agents_concrete.py` planner-message assertions).

### Phase 2 — Code Author renders the orientation cell (persona-only; the primary change)
- Edit `personas/code_author.md` output-format rule: the **first markdown cell is a learner
  orientation**, distinct from a topic summary. It must contain, calibrated to `material_density`:
  1. the goal in **plain pre-jargon language**, one or two sentences;
  2. a **plain-language roadmap** with two facets, both leading with everyday language (Design
     decision 4): **what the notebook does** beat by beat, and **what you should be able to
     understand afterward** as plain capabilities — survey altitude, no concept re-teaching. Where a
     topic term is unavoidable, give the plain phrase first with the real term in parentheses
     (*plain-first, jargon-in-brackets*); never a bare acronym alone. Full explanations stay inline,
     later.
  3. **"What this assumes / your likely gap"**, built from the plan's `KNOWN`/`GAP` map: name the
     assumed-known items as a quick confidence check, and call out the single `GAP` that most unlocks
     the notebook ("if you've never seen X, slow down at the primer — it's the keystone").
- Keep the existing inline gap scaffolding (rule 5) unchanged; add an explicit **anti-redundancy**
  note: the orientation frames, the inline cells teach — do not repeat the concept body up top.
- Gate honored: when the plan reports no `GAP`s, the cell is a one-line framing.
- Tests (golden-ish, persona-behavior level): see Part IV.

### Phase 3 — Optional deterministic backstop (decide after Phase 1–2 land)
Mirror the R1 stance: personas are the fix, a cheap deterministic check is the honesty backstop.
A minimal `nbformat`-only assertion that the first markdown cell exists and references at least one
assumed/gap term from `topic_spec` / plan **may** be added next to `structure.py`'s anti-hollow check.
**Deferred under YAGNI** unless persona output proves unreliable — do not build speculatively.

### Phase 4 — Docs & close-out
- Flip this doc to IMPLEMENTED with validating test names.
- Sync `TODO.md` (add under output-quality / learner-fit; note the R1 adjacency).
- Run all three CI gates; address reviewer-on-diff findings.

---

## Part IV — Acceptance

- [x] The Code Author persona requires the first markdown cell to be a learner **orientation**
      stating the goal in plain pre-jargon language and naming the assumed-known items + the
      most-unlocking gap from the plan's `KNOWN`/`GAP` map. — `personas/code_author.md` "Learner
      orientation" section; `test_orientation_persona.py::test_code_author_persona_first_cell_is_learner_orientation`,
      `::test_code_author_persona_surfaces_assumed_and_gap`.
- [x] The orientation requires a **plain-language roadmap** covering both *what the notebook does*
      and *what the learner should understand afterward*, leading with everyday language, with any
      topic term plain-first and the real term in parentheses (never a bare acronym). —
      `test_orientation_persona.py::test_code_author_persona_roadmap_has_both_facets`,
      `::test_code_author_persona_requires_plain_first_jargon_in_brackets`.
- [x] The persona reserves teaching for the inline cells (altitude discipline / anti-redundancy):
      the orientation "frames; it does not teach." — `personas/code_author.md` "Learner orientation"
      section (no separate assertion; enforced by persona prose + Reviewer-on-diff).
- [x] The gate: when the plan reports **no** `GAP`s the orientation collapses to a one-line framing.
      — `personas/planner.md` gate clause + `personas/code_author.md` gate clause;
      `test_orientation_persona.py::test_planner_persona_gates_orientation_on_gaps`.
- [x] Persona-contract tests for Planner (orientation deliverable + gate) and Code Author (first-cell
      orientation shape) pass. — `tests/pipeline/test_orientation_persona.py` (6 tests).
- [x] CI gates green (`ruff`, `mypy`, coverage 92.4% ≥ 80%).

> **Not unit-verified (by design):** whether the LLM's *generated* notebook honors these rules at
> runtime is a persona-behavior outcome, not a deterministic contract. Phase 3 sketches an optional
> `nbformat`-only backstop (first cell exists, plain-first ordering) — deferred under YAGNI until
> generated output proves unreliable. Reviewer-on-diff is the interim check.

---

## Part V — Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Redundancy with existing overview + inline scaffolding | MEDIUM | Altitude discipline in persona; explicit anti-redundancy rule; Reviewer-on-diff |
| Persona edit doesn't reliably change LLM output shape | MEDIUM | Persona-contract tests; optional Phase-3 deterministic backstop if needed |
| Orientation re-introduces jargon and re-fails the learner | MEDIUM | *Plain-first, jargon-in-brackets* rule with a concrete example in the persona — plain phrase always precedes the real term, never a bare acronym |
| Bloats short/simple notebooks | LOW | Gap-analysis gate collapses it to one line when there are no `GAP`s |
| Coverage dips from any new module (Phase 3) | LOW | TDD per phase; Phase 3 is deferred/optional |

---

## Relationship to R1 (`11-topic-fidelity-r1.md`)

R1 and this feature are the two halves of **prerequisite/scope honesty**:

- **R1 — honesty about output:** never *silently* drop a capability the topic requested.
- **This — honesty about input:** never *silently* assume a prerequisite the learner lacks; surface
  the Planner's existing gap map to the learner up front.

Both follow the same principle: the pipeline already computes the truth; the fix is to **surface it**
instead of letting it die in an intermediate artifact. No coupling beyond that shared philosophy.

---

## References
- `runs/localLLM-r1-validate/lesson_notebook_v3.ipynb` — cell 0, the topic-summary-not-orientation
- `runs/localLLM-r1-validate/lesson_plan_v0.md` — the `KNOWN`/`GAP` map that should reach the learner
- `runs/localLLM-r1-validate/student_grade_report_v3.json` — `learner_fit: 75`, `explanation_depth: 65`
- `personas/planner.md` — `## Required background & gaps` (source of the gap map)
- `personas/code_author.md` — rule 5 (inline scaffolding) + output format (existing overview cell)
- `docs/architecture/11-topic-fidelity-r1.md` — the output-side honesty counterpart
