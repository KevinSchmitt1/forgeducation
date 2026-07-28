# 17 — Lesson Modes (teach artifact-based topics without gutting the honesty guarantee)

**Status:** ✅ IMPLEMENTED (2026-07-28) on `feat/lesson-modes`. This doc is the design of record and
the shared contract every stage builds against. All stages wired; suite green (631 passed, 92.8%
coverage; `mode.py` and `failure.py` at 100%). **Not yet validated end-to-end on a live paid run** —
the unit/integration tests prove the plumbing, but that the LLM planner *actually infers* `artifact`
mode on a real agentic-AI topic is a paid run tracked in `TODO.md`, run only with explicit consent.

> Planning header: mode is **purely planner-inferred** — no user-facing field, no CLI flag, no
> template change. Automation is the point: the learner types a topic, the program decides how to
> teach it.

## Problem

forgeducation's defining guarantee is a **runnable, self-checked** notebook: a stage actually
executes the notebook and the critics check explanations against what the cells really did. That
guarantee is enforced today by (a) the executor running every cell, and (b) the deterministic
anti-hollow gate in [`structure.py`](../../forged/pipeline/structure.py) refusing to call a notebook
ACCEPTABLE if its code never demonstrated anything.

This makes an entire class of legitimately *technical* topics unteachable. "Working with agentic AI"
has plenty of "code" — agent definitions, persona `.md` files, framework wiring, an agentic-loop
harness, a project file tree, a strategy for agents that learn with the user — but almost none of it
is **compute-and-show Python** you run cell-by-cell to see a number pop out. The current personas
mandate "every code cell must actually run … the learner must SEE it work"
([`code_author.md`](../../personas/code_author.md)), so the program either force-fits toy code or
produces a hollow lesson. Neither teaches the topic.

## Key insight

Agentic-AI topics are not "no code" — they are **artifact code**. Writing `agents/researcher.md`,
scaffolding a file tree, wiring a framework, defining a loop harness — each of these can be
**produced by a cell** and **validated by a cell** (does the `.md` parse and carry the required
sections? does the scaffold contain the declared files? does the harness dry-run against a *mocked*
LLM?). So we do not abandon execution — we **broaden what execution verifies**. The self-check
survives; only its target changes. That is what keeps this honest.

## Design: three lesson modes

The planner infers exactly one mode per lesson and declares it in a machine-readable tag.

| Mode | Deliverable | "Seeing it work" = | Honesty check (deterministic) |
|---|---|---|---|
| `executable` (default) | compute-and-demonstrate Python | a cell produces real output | execution + existing anti-hollow output gate — **unchanged** |
| `artifact` | files / config / scaffold / persona `.md` / loop harness | a cell **writes** the artifact and a cell **validates** it (parse / structure / lint / mocked dry-run) | ≥1 code cell actually ran and validated an artifact (produced real output); real explanatory prose |
| `conceptual` (rare fallback) | prose + diagrams only | n/a — nothing runs | explanation-quality + structure only; SUMMARY states plainly **"no code was executed"** |

`executable` is the conservative default: if the planner declares nothing, or declares something
unrecognized, the lesson is treated as `executable` and the full existing rigor applies. A topic must
be *clearly* artifact- or concept-shaped to leave the default.

## The contract (what every stage agrees on)

### 1. Machine-readable tag (mirrors the `requirements` block)

The planner emits, in its plan markdown, a fenced block — exactly one lowercase word:

````markdown
```lesson-mode
artifact
```
````

Allowed words: `executable` | `artifact` | `conceptual`. This mirrors the existing
` ```requirements ` convention that [`dependencies.py`](../../forged/pipeline/dependencies.py) already
parses, so there is one house style for machine-readable planner signals.

### 2. Deterministic extractor — `forged/pipeline/mode.py` (NEW)

Mirrors `dependencies.py` and `structure.py`: **stdlib + `re` only, no imports from other pipeline
modules** (so `structure.py` / `failure.py` / `reviser.py` can import it without a cycle).

```python
LessonMode = Literal["executable", "artifact", "conceptual"]
DEFAULT_MODE: LessonMode = "executable"

def extract_lesson_mode(plan_text: str) -> LessonMode:
    """First ```lesson-mode block wins; unknown/absent → DEFAULT_MODE."""
```

Conservative by design: anything ambiguous falls back to `executable`, never the other way — we
never silently drop rigor from a topic that deserved it.

### 3. Where mode is read (no state field, no threading)

Mode is derived from the plan artifact wherever it is needed. It is **not** added to
`PipelineState` or `TopicSpecification`.

- **Reviser** ([`reviser.py`](../../forged/pipeline/agents/reviser.py)) — the single deterministic
  integration point; it already invokes both `assess_structure` and `classify`. It reads the latest
  `lesson_plan_v{N}` artifact, calls `extract_lesson_mode`, and passes the mode into both.
- **LLM grader personas** (student, reviewer) — they already read the plan in-context, so they see
  the declared mode and its artifact-deliverable sequence directly. Persona edits only; no code.
- **SUMMARY writer** ([`deliverables.py`](../../forged/pipeline/../deliverables.py)) — reads the plan
  file from the run dir, reports the mode and which verification ran.

### 4. Mode-aware verification

- `assess_structure(notebook_content, lesson_mode="executable")`
  - `executable`: **unchanged**.
  - `artifact`: hollow unless ≥1 code cell actually ran and produced real output (an artifact was
    built/validated for real); the prose check still applies. Non-running *reference* cells are not
    penalized (they already count as neither executed nor skipped).
  - `conceptual`: no code expected; verdict rests on the prose/structure check; the report records
    that nothing executed so SUMMARY can say so honestly.
- `classify(..., lesson_mode="executable")`: in `artifact`/`conceptual` modes, "nothing runnable
  executed" is **not** an execution failure. Every other route (blocker, quality, hollow) is
  unchanged. The hollow backstop still fires — with the mode-aware definition above.

## Didactical shift (personas)

- **Planner** ([`planner.md`](../../personas/planner.md)) — infer the mode from the topic and
  *justify* it; when not `executable`, replace the "Code demonstration" section with an
  **artifact / deliverable sequence** (what gets built, in what order, and how each piece is
  validated). Still lists `requirements` (validation deps: a YAML/markdown parser, a mock, a linter).
- **Code Author** ([`code_author.md`](../../personas/code_author.md)) — mode-aware. In `artifact`
  mode "every cell must run / the learner must SEE it work" is **reinterpreted, not dropped**: cells
  *write* artifacts and *validate* them, and each artifact cell is followed by prose explaining what
  was created, where, and why it matters. Reference code may be shown without running, but at least
  one cell must build-and-validate for real.
- **Student & Reviewer** ([`student.md`](../../personas/student.md),
  [`reviewer.md`](../../personas/reviewer.md)) — grade an artifact lesson on its own terms: is the
  artifact correct, complete, and explained? Do not demand a runnable compute demo the mode never
  promised.

## Non-goals / guardrails

- **Not** a way to skip execution. `artifact` mode still runs and validates cells; `conceptual` mode
  is a rare fallback that is *loudly* honest that nothing ran.
- **Not** user-configurable. Mode is inferred; there is no override knob (deliberate — automation).
- The honesty machinery (degradations, topic-fidelity, hollow backstop) is **extended**, never
  bypassed.

## Files

| File | Action | Why |
|---|---|---|
| `docs/architecture/17-lesson-modes.md` | CREATE | this doc — contract of record |
| `forged/pipeline/mode.py` | CREATE | deterministic mode extractor (mirrors `dependencies.py`) |
| `tests/pipeline/test_mode.py` | CREATE | extractor unit tests |
| `forged/pipeline/structure.py` | UPDATE | mode-aware anti-hollow verdict |
| `forged/pipeline/failure.py` | UPDATE | thread mode; don't misfire execution-failure in non-executable modes |
| `forged/pipeline/agents/reviser.py` | UPDATE | extract mode from plan; pass to assess + classify |
| `forged/deliverables.py` | UPDATE | SUMMARY reports mode + verification kind |
| `personas/planner.md` | UPDATE | infer + declare mode; artifact deliverable sequence |
| `personas/code_author.md` | UPDATE | mode-aware authoring |
| `personas/student.md`, `personas/reviewer.md` | UPDATE | grade artifact lessons on their terms |

## Validation

- `.venv/bin/python -m pytest` (esp. new `tests/pipeline/test_mode.py`, existing `test_pipeline.py`)
- `.venv/bin/ruff check forged tests`
- `.venv/bin/mypy`
- `.venv/bin/python -m pytest --cov=forged --cov-fail-under=80`

End-to-end confirmation that the planner *actually* infers `artifact` on a real agentic-AI topic is a
**paid run**, tracked separately and run only with explicit consent.
