# 18 — Mode-selection bias and run honesty (findings from the 2026-07-28 course run)

**Status:** ✅ IMPLEMENTED (2026-07-30) on `feat/mode-selection-debias` — D1–D6 all landed, three CI
gates green locally. **Not yet validated on a live paid run**: whether the debiased planner actually
emits a *mix* of modes is the open question, and it can only be answered by the re-run described
under [Validation](#validation). This doc is the design of record for the remediation; it is also the
first end-to-end *observed* validation of the lesson-mode machinery designed in
[`17-lesson-modes.md`](17-lesson-modes.md).

**Implementation notes (what differed from the design):**

- **D4** — the prose miner was removed outright, so the "stopword check on every token" hardening
  became moot: there is no surviving prose-mining path for it to guard. A new
  `RequirementSet.source == "malformed"` distinguishes *"the planner's block was garbage"* from
  *"the planner declared no dependencies"*, and `provision_environment` checks it **before** the
  "no requirements → base kernel" branch (a malformed block also has zero requirements and would
  otherwise have been silently treated as "nothing needed").
- **D4 residual risk** — the unfenced-heading regex matches any line whose sole content is
  `requirements` (optionally `##`-prefixed). A plan using `## Requirements` as an ordinary *prose*
  section would now be read as a dependency block and likely reported malformed. Accepted as narrow
  given the planner's observed convention (`## Prerequisites` as the parent section, bare
  `requirements` as the embedded machine block), but it is the known sharp edge here.
- **D6** — the hard-vs-degraded distinction keys off `state.is_terminal and state.terminal_ok`,
  which `PipelineState.terminal_ok`'s own docstring already defined; it is the same condition
  `write_agentic_summary` used for its ✓/✗ line, now factored into a shared helper. `COURSE.md`
  reads the reason from the module's `FAILED.md` stub rather than plumbing a new `ModuleResult`
  field, keeping the reason single-sourced.
- **D3** — the interactive gate already existed (doc 16) but was wired only into `learn`. `course`
  ran ungated; Phase 5 wired it, and `course` now requires `--yes` on a non-TTY exactly as `learn`
  has since doc 16. This is a **behavior change** for scripted `course` invocations.

  **Correction:** an earlier draft of this doc claimed the 2026-07-28 run itself went through that
  ungated path. It did not — Kevin ran `learn`. The `course_` run-directory prefix is *not* evidence
  of the command: `_build_confirmed` (the `learn` N-module branch,
  [`cli.py`](../../forged/cli.py)) and `_cmd_course` both name their output
  `{stamp}_course_{topic-slug}`. So that run **was** gated and confirmed. What the gate could not
  show was how each module would be *taught*: modes did not exist on `ModuleSpec` and were inferred
  per module by the lesson planner only after the build began. The gate had nothing to display and
  the operator nothing to veto — which is what D3 fixes. Wiring `course` to the gate remains a real
  hole worth closing; it just was not this run's hole.
- **D3** — mode override rides in the existing `AdjustmentIntent` (`op="set_mode"`, one target) with
  the mode word parsed deterministically from the learner's sentence, rather than widening the
  adjuster's JSON schema. No second LLM call to read one word. `set_mode` is therefore the one
  carve-out from the adjuster's "echo the sentence verbatim" rule: its `instruction` carries the
  *resolved* mode word alone, so "less code in the last one — just explain it" resolves to
  `conceptual` instead of being rejected for containing no literal mode word.

**Fixed during review of this change (all three were live defects, not hypotheticals):**

- **Silent truncation in the unfenced block.** `_parse_body` skips `#` comment lines the way
  requirements.txt does, but the heading scan *terminated* on the first one — so
  `requirements / numpy / # core lib / pandas` silently yielded `numpy` alone, with no error and no
  `malformed` flag. Exactly the silent-drop class D4 exists to eliminate, reintroduced by D4 itself.
  Only a markdown **section** heading (`##`+) ends the block now; a single `#` is a comment.
- **Negation inverted the mode override.** `re.findall(r"[a-z_]+", …)` splits on `-`, so
  "make module 2 non-executable" tokenized to `{non, executable}` and confidently applied
  `executable` — the opposite of the request, with no crash and no re-prompt. Negated modes now
  raise and re-prompt.
- **Persona self-contradiction.** `plan_adjuster.md` cited "less code in the last one — just explain
  it" as valid `set_mode` phrasing while the global rule told the model to echo sentences verbatim;
  the deterministic parser would then have rejected that very example. Resolved by the carve-out above.

> **Headline:** the lesson-mode machinery works and its critics are fair. The planner never uses it —
> it declared `executable` **8 out of 8 times**, correctly fenced, including for a module whose stated
> objective is "design a local project and file layout." Everything the learner complained about
> (too code-heavy, not practical, wrong subject matter) traces back through that single decision.

## Source

Learner feedback on `runs/20260728-145848_course_teach_me_how_to_work_with_ai_a/`, recorded by Kevin
in that run's `feedback.md`, verbatim:

1. `MockLLM` is unclear for learners; label it explicitly as a local fake/demo LLM class, not a real
   model or library.
2. Not very practical — the point of teaching how agents work in general is understood, but the ask
   was more concrete: how to build agents in Claude Code, how to build meaningful and useful skills,
   how to build on past projects and enhance productivity, which folder architecture and data
   structure to use.
3. The notebook of module 1 is not working because of missing packages.
4. Very code-heavy, even though the topic was highly practical.

Original topic (raw `--topic`):

> Teach me how to work with AI agents: how to build them, build harnesses for them, and optimize
> agentic workflows. At the same time, teach me how to optimize my own workflow with AI and make my
> AI setup learn together with me — meaning how I manage all the files and data on my machine, and
> how the architecture of that should look.

This run is the paid validation of `feat/lesson-modes` that `TODO.md` was waiting on ("Run B"). Its
predicted failure signal fired exactly as written: *"If it still force-fits runnable compute cells or
picks `executable`, that's the finding to report."*

## Evidence

### E1 — Every module chose `executable`, deliberately

All eight emitted plans (`lesson_plan_v*.md` across four modules) carry a **correctly fenced**
` ```lesson-mode ` block, and every one of them says `executable`. This is not a parse failure — the
extractor in [`mode.py`](../../forged/pipeline/mode.py) read exactly what the planner meant.

Module 3 is the clearest miss. Its objectives are "design a scalable local project layout" and "file
and data architecture for AI projects"; its requirements are `sentence-transformers`, `faiss-cpu`,
`scikit-learn`, `numpy`. Those packages are **computable proxies standing in for an architectural
subject**.

### E2 — Code share by line count

| Module | code lines | md lines | code % | mode |
|---|---|---|---|---|
| 0 Agent Fundamentals | 385 | 124 | **76%** | `executable` |
| 1 Building Agent Harnesses | 471 | 103 | **82%** | `executable` |
| 2 Optimizing Agentic Workflows | 463 | 57 | **89%** | `executable` |
| 3 Personal Workflow Architecture | 316 | 82 | **79%** | `executable` |

"Very code-heavy" is measurable, uniform, and worst in the module with the least computable subject.

### E3 — Module 1 died on allow-list curation lag

`SUMMARY.md`: `Refusing to provision: package(s) outside the allow-list: openai, faiss-cpu, pytest`.

[`DEFAULT_ALLOWED_PACKAGES`](../../forged/provisioning.py#L53-L69) carries 60+ scientific/ML
packages and **none of the agent stack** — no `openai`, `anthropic`, `faiss-cpu`, `langchain`,
`chromadb`, `pytest`, `python-dotenv`, `gitpython`. The list was curated for the ML-topic era. The
program cannot currently teach the domain it is named after.

### E4 — Module 3 died on fabricated packages

`SUMMARY.md`: `Refusing to provision: package(s) outside the allow-list: not, required, for, the, core`.

Root cause chain:

1. The planner wrote its requirements block **without the code fence** — bare `requirements` at
   `module_3/lesson_plan_v3.md:36` (and v0, v1), instead of ` ```requirements `.
2. `_FENCE_RE` in [`dependencies.py`](../../forged/pipeline/dependencies.py) matched nothing, so the
   real, well-formed, one-per-line list (`sentence-transformers`, `faiss-cpu`, `scikit-learn`,
   `numpy`, `GitPython`, `python-dotenv`) was **never read**.
3. The prose fallback mined this sentence four lines below it:
   > ``(If you plan to run DVC flows, install dvc separately: `pip install dvc` — not required for the core demo.)``
4. `_PROSE_LEAD_WORDS` only tests the **first** token after `pip install`. That token was `` dvc` ``,
   which is not a function word, so the guard passed and the remaining English words became
   "packages."

**Severity note:** `core`, `the`, `not` and `required` are all **real, live PyPI packages** (HTTP 200;
only `for` 404s), and [`provisioning.py:268`](../../forged/provisioning.py#L268) runs a plain
`pip install --no-input` with no `--only-binary`, so an sdist's `setup.py` executes as the user. The
allow-list was the only thing between a fabricated LLM token and arbitrary code execution. It held —
but by curation, not by design.

Note also that within *the same file*, the planner fenced `lesson-mode` correctly and `requirements`
incorrectly. Fence emission is sporadic, not systematically broken — so the parser must tolerate it;
persona instruction alone will not.

### E5 — Failures shipped quietly

`COURSE.md` reports **"Modules: 2/4 completed"** as an ordinary status line. The run `README.md`
shows bare `Status: ✗` for modules 1 and 3 with no reason, no missing-package list, and no pointer to
`SUMMARY.md`. A `lesson.ipynb` was written for both failed modules anyway — so the learner's first
signal that anything was wrong was an `ImportError` at their own keyboard.

Course-level plan-fidelity reported `⚠ DROPPED` **for the entire raw topic**, printed at the bottom
of `COURSE.md` after the money was spent, and routed nowhere.

Note this run was launched with `learn`, so the doc-16 plan gate *did* run and the plan *was*
confirmed. Everything above happened downstream of that confirmation: the gate showed module titles
and objectives, but nothing about how each module would be taught, and the failures surfaced only
after the build. Gating is necessary but was not sufficient — the gate has to display the decision
that actually goes wrong.

### E6 — Unrelated degradations surfaced (not in the learner's feedback)

Recorded for triage, not necessarily in this scope:

- `code_author` (`llm_empty_fallback`): `finish_reason='length'` on gpt-5 — module 2.
- `code_author` (`llm_empty_fallback`): `Connection error` on gpt-5 — module 3.
- `reviewer` (`review_failed`): `finish_reason='length'` on gpt-5-mini — modules 2 and 3.

Two distinct issues: an output-token ceiling being hit on the expensive stage, and no retry on a
transient connection error.

## Key insight — the causal chain

The four feedback items are not four problems. They are one decision and its consequences:

```
planner persona is biased toward `executable`
        │
        ▼
"how should I lay out a Claude Code project" has no runnable compute demo
        │
        ▼
planner substitutes a computable proxy (FAISS, embeddings, A/B tests)
for the actual subject (Claude Code agents, skills, folder architecture)
        │
        ├──▶ subject drifts generic  ────────▶ "not practical"        (feedback 2)
        ├──▶ cells fill with proxy code ─────▶ "very code heavy"      (feedback 4)
        └──▶ proxies need heavy deps ────────▶ allow-list rejections  (feedback 3)
```

The topic was not abstracted and then coded. **It was abstracted in order to be codeable.**

Consequence for sequencing: fidelity drift is a *symptom* here. Fix mode selection, re-run, and
re-measure fidelity **before** building any fidelity-routing machinery, or we risk building a
subsystem for a problem that dissolves.

## What is NOT wrong (do not rebuild this)

An early hypothesis — that the critics' rubrics punish non-executable lessons, giving the planner a
rational incentive to avoid them — was **checked and disproved**. Mode-awareness is already
implemented and even-handed across the whole downstream pipeline:

| Component | Mode handling |
|---|---|
| [`structure.py:157-179`](../../forged/pipeline/structure.py#L157-L179) | separate "hollow" definitions per mode |
| [`failure.py:294-326`](../../forged/pipeline/failure.py#L294-L326) | missing execution is not a failure outside `executable` |
| [`student.md:68-75`](../../personas/student.md#L68-L75) | "do not penalize the lesson for lacking a runnable compute demo" |
| [`reviewer.md:44-53`](../../personas/reviewer.md#L44-L53) | "Do NOT demand numeric compute output that the mode never promised" |
| [`code_author.md:51-66`](../../personas/code_author.md#L51-L66) | artifact-mode "SEE it work" = artifact builds and passes validation |

**Rejected:** adding mode-specific agents, swapping agents in the loop per mode, or redefining the
`code_author`/`student`/`reviewer` layers. That work is already done and fair. The defect is isolated
to the planner's *decision*, which is ~15 lines of persona text.

## Design decisions

### D1 — Debias the planner's mode section (the core fix)

[`planner.md:31-52`](../../personas/planner.md#L31-L52) stacks five independent nudges toward the
default, plus a sixth implicit one:

> `executable` **(default)** … **Stay here unless** the brief is **clearly** artifact- or
> concept-shaped … `conceptual` **(rare)** … **Be conservative:** an ambiguous or borderline brief
> **stays `executable`** … **Only** move to artifact or conceptual when the deliverable is
> **clearly** not runnable compute … don't reach for **the exception**

…and the illustrative fenced block literally contains the word `executable`, anchoring the answer
few-shot style.

That defensiveness was correct **when written** — the other two modes had no rigor behind them yet.
Doc 17 built that rigor; this section never got the memo. Rewrite it to select on the *deliverable's
actual shape* with no thumb on the scale, and change the illustrative block so it does not anchor.

### D2 — Modes are per-module and expected to differ

A course whose modules all share one mode is a smell. The planner must decide each module's mode from
**that module's** deliverable, not inherit it from the course. Kevin's expected shape for this topic:
module 0 executable (the technical background — which he explicitly liked), one or more `artifact`,
at least one `conceptual`.

### D3 — Interactive plan gate

The gate must let the operator **override modes in place and continue** — not print and abort. Ctrl-C
means re-paying for the planning pass, which is why "informative only" was rejected.

Minimum viable, deliberately small (a UI comes later):

- show the module count, each module's title, and its inferred mode
- show the course-level topic-fidelity verdict **here**, before spend — not at the end
- flag homogeneous-mode courses explicitly
- allow editing a mode, then proceed
- non-interactive/CI path keeps today's behavior

### D4 — Requirements parsing: tolerate the format, distrust the prose

- **Accept the unfenced heading form** (`requirements` alone on a line, followed by requirement-shaped
  lines). This alone fixes module 3 — the miner never runs.
- **Remove the `pip install` prose miner.** It is the sole source of fabricated packages and was never
  the contract. A missing dep fails loudly; a fabricated one fails confusingly and dangerously.
- **Apply the stopword check to every token**, not just the lead, for as long as any fallback exists.
- A malformed requirements block must report itself as *"the plan's requirements block is malformed"*,
  never as a policy violation — E4 hid a parser bug behind a security message for two days.

**Rejected:** replacing the allow-list with a PyPI existence/maturity check plus interactive consent.
Considered and dropped as over-engineered and bug-prone for the benefit — the list has worked well in
practice, and its one real failure (E3) is curation lag, fixed by curating.

### D5 — Widen the allow-list to the agent stack

Data change: `openai`, `anthropic`, `faiss-cpu`, `pytest`, `python-dotenv`, `gitpython`, `chromadb`,
`langchain` and neighbours. Deliberate and reviewed, per the existing comment's instruction.

### D6 — Honest failure reporting

- **Do not write `lesson.ipynb` when the module failed.** The `lesson_notebook_v*.ipynb` files remain
  for inspection; the missing canonical filename is itself the signal.
- Write a short failure stub naming what was refused and what is missing.
- Surface the reason inline in the module `README.md` and in `COURSE.md`, replacing the bare `✗`.
- **Unchanged:** a failed module must not stop the others. This behavior is explicitly valued.

## Validation

Offline (all three CI gates green) covers D1–D2 partially and D3–D6 fully. The payoff needs **one
paid re-run of this same topic**, checking in order:

1. Does the planner now emit a **mix** of modes (not 4×`executable`)?
2. Does the plan gate show it, and can a mode be overridden without re-planning?
3. Does the subject stay concrete about the named tool instead of drifting to computable proxies?
4. Does code share drop from the 76–89% band?
5. Do all four modules provision?

Success on 1–3 would confirm the causal chain and retire the fidelity-routing question. Failure on 3
while 1 passes would prove fidelity is an independent defect and re-open it as its own doc.

## Validation result (2026-07-30 re-run)

Run: `runs/20260730-215250_course_teach_me_how_to_work_with_ai_a`, same topic, same learner profile,
via `learn`, unconstrained.

**Criterion 1 — PASS.** The course planner emitted a **mix**, and assigned `artifact` to precisely
the module that had FAISS force-fitted into it before:

| Module | Mode |
|---|---|
| 0 — Implementing and Evaluating AI Agents and Harnesses | `executable` |
| 1 — Designing an AI-First Personal Workflow and Continuous Co-Learning | **`artifact`** |

It also sized down from four modules to two. The hand-down worked end to end: module 1's
`lesson_context.md` carries the binding `artifact` directive. After 8/8 `executable`, the persona
debias (D1) is confirmed to change real behavior.

**Criteria 3–5 — unmeasurable**, because module 1 crashed (below) and criterion 4's signal lived in
that module. Module 0 is 80% code, which is *legitimate* for an `executable` lesson — the code-share
metric only means something across a mixed course.

### Two defects this run exposed

**F1 — a crashed module destroyed its own evidence.** Module 1 raised inside `run_pipeline`. Two
independent gaps meant nothing survived:

- `_run_one_module`'s `except` path returns **before** `_write_module_deliverables`, so neither
  `SUMMARY.md` nor D6's `FAILED.md` was written. D6 only ever covered "completed but unacceptable";
  "raised" is a different path and was never handled.
- `setup_logging` is called only in `_run_agentic_lesson` (the *single-lesson* CLI path). The course
  orchestrator configured no logging at all, so `_LOG.exception(...)` went to a handler-less logger
  and the traceback was **discarded**.

The module left only its seed files, and the cause is permanently unknowable. Fixed: the orchestrator
now calls `setup_logging` per module (each gets its own `pipeline.log`) and writes a crash stub via
`write_crash_stub` carrying the exception type, message, and full traceback.

**F2 — the course-level fidelity check was structurally incapable of passing on a free-text topic,
and this doc cited its output as evidence.** E5 above notes the `⚠ DROPPED` line for the whole raw
topic. That is an **artifact, not drift**. Demonstrated: feeding a haystack that plainly covers the
topic still returns `0 covered, 2 missing`. Two compounding causes:

1. `_default_topic_spec` put the raw topic into **both** `learning_objectives`
   (`f"Understand {topic}"`) and `focus_areas` (`topic`). Distinctive terms are computed *among* the
   requested set, so the near-duplicate pair cancelled to the single term `understand` — a word no
   module title contains. Fixed: `focus_areas` no longer repeats the topic.
2. Term-coverage assumes a **capability statement** ("train a LoRA adapter"), not a 60-word brief,
   whose distinctive-term set is dominated by connective words no module title carries. Fixed:
   `assessable_capabilities` (`MAX_ASSESSABLE_CAPABILITY_WORDS = 30`) filters paragraph-shaped
   entries, and the verdict gained a third outcome — **`ⓘ not assessed`** — because claiming a drop
   that was never measured, or a ✓ that was never earned, are both dishonest.

A short topic stays assessable, so genuine drop detection still works (covered by test).

**Correction to E5 above:** the course-level `⚠ DROPPED` line is *not* evidence of subject drift and
should not be read as such in this doc. The per-module `⚠ still dropped` lists are different — those
come from the R1 detector against each module's own spec — and remain real signal.

## Deferred

- Topic-fidelity **routing** (DROP → replan). Gated on validation step 3 above.
- Course sizing — whether a narrow, tool-specific topic should yield fewer, more specific modules
  rather than four broad ones. Suspected downstream of D1; re-measure after.
- E6's token-ceiling and retry defects — real, separate, out of this scope.
- `--only-binary=:all:` for install-time code-execution hardening.
