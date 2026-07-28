"""Deterministic structural assessment of an executed notebook.

This is the anti-hollow backstop. The executor only reports whether cells *ran*;
it cannot tell "ran and demonstrated the concept" from "ran but skipped all the
substance behind `if HAVE_DEPS:` guards". A notebook full of "… skipped: missing
torch" lines executes green yet teaches nothing — exactly the failure mode that
let the localLLM run ship a hollow lesson while reporting ok=True.

assess_structure() reads the executed notebook (markdown + code cells *with their
real outputs*) and decides, with no LLM and no randomness, whether the lesson is
hollow. The classifier uses this to refuse to mark a hollow notebook ACCEPTABLE.

Mode-aware (docs/architecture/17-lesson-modes.md): not every lesson is
compute-and-show Python. ``lesson_mode`` changes what "hollow" means without
weakening the check — it only ever retargets what execution must demonstrate:
  * ``executable`` (default) — unchanged: a real demonstration means a code cell
    produced real output, and a majority-skipped notebook is still hollow.
  * ``artifact``   — the deliverable is a file/config/scaffold; hollow unless at
    least one code cell actually ran and produced real output (built/validated
    something for real). Non-running reference cells are not penalized.
  * ``conceptual`` — no code is expected; the code-based checks never fire. The
    verdict rests only on the prose/section check, and the report still carries
    the real metrics so the run summary can say plainly that nothing executed.

Dependency: nbformat + stdlib only, plus forged.pipeline.mode (also stdlib-only,
so this stays acyclic — failure.py can import StructuralReport without a cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import nbformat

from forged.pipeline.mode import LessonMode

# ── Tunable thresholds ─────────────────────────────────────────────────────────

# A lesson with fewer than this many "# heading" markdown cells AND barely any
# prose is treated as having no real explanation.
MIN_SECTIONS = 2
MIN_MARKDOWN_WORDS = 30
# When at least half of the code cells merely printed a skip message, the lesson's
# substance never ran — it is hollow regardless of a green execution report.
SKIP_FRACTION_THRESHOLD = 0.5
# A guarded skip prints a brief one-line message ("X skipped: missing torch").
# We only treat a cell as skipped when its output is this short, so the word
# "skipping" appearing inside a large, genuinely-produced output never counts.
SKIP_MAX_OUTPUT_CHARS = 200

# Output text that marks a cell as a no-op skip rather than a real demonstration.
# Deliberately narrow to avoid false positives on legitimate teaching output:
#  - only the verb forms "skipped"/"skipping" (not the bare noun "skip"/"skips",
#    which appears in "[SKIP] token", "skips ahead", etc.),
#  - excluding zero-count reports like "rows skipped: 0" / "Skipped 0 batches",
#  - plus the setup-cell "missing prerequisite(s)" wording.
_SKIP_RE = re.compile(
    r"\bskip(?:ped|ping)\b(?!\s*:?\s*0\b)|missing prerequisite",
    re.IGNORECASE,
)


# ── Result ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StructuralReport:
    """Deterministic verdict on whether an executed notebook teaches anything.

    is_hollow is True when the lesson executed but does not actually demonstrate
    its topic. reasons explains why (one human-readable line per failed check),
    and is surfaced in the run summary. The remaining fields are the raw metrics
    the verdict was derived from, for auditability.
    """

    is_hollow: bool
    reasons: tuple[str, ...] = ()
    section_count: int = 0
    code_cell_count: int = 0
    executed_count: int = 0
    skipped_count: int = 0
    markdown_word_count: int = 0


# ── Assessment ─────────────────────────────────────────────────────────────────


def _has_header(source: str) -> bool:
    """True when any line of the markdown cell is a '#' heading."""
    return any(line.lstrip().startswith("#") for line in source.splitlines())


def _output_text(outputs: list) -> str:
    """Concatenate the human-readable text of a code cell's non-error outputs."""
    texts: list[str] = []
    for output in outputs:
        otype = output.get("output_type")
        if otype == "stream":
            texts.append(output.get("text", ""))
        elif otype in ("execute_result", "display_data"):
            data = output.get("data", {})
            if "text/plain" in data:
                texts.append(data["text/plain"])
    return "".join(texts)


def assess_structure(
    notebook_content: str, lesson_mode: LessonMode = "executable"
) -> StructuralReport:
    """Assess whether an executed notebook is structurally hollow.

    Args:
        notebook_content: nbformat JSON of the EXECUTED notebook (cells carry
            their real outputs). Use the executed copy, not the pre-run notebook,
            so skip messages and produced outputs are visible.
        lesson_mode: what kind of lesson this is (docs/architecture/17-lesson-modes.md).
            Only changes what counts as a real demonstration; the prose/section
            check always applies. Defaults to ``"executable"`` — the historical,
            unchanged behavior — so every existing caller is unaffected.

    Returns:
        A StructuralReport. is_hollow is True when the lesson ran but does not
        demonstrate its concept — the concrete meaning of "demonstrate" depends on
        lesson_mode (see module docstring). The raw metrics (section_count,
        executed_count, etc.) are always populated regardless of mode, so a
        conceptual lesson's report still honestly states that nothing executed.
    """
    notebook = nbformat.reads(notebook_content, as_version=4)
    markdown_cells = [c for c in notebook.cells if c.cell_type == "markdown"]
    code_cells = [c for c in notebook.cells if c.cell_type == "code"]

    section_count = sum(1 for c in markdown_cells if _has_header(c.source))
    markdown_word_count = sum(len(c.source.split()) for c in markdown_cells)

    executed_count = 0
    skipped_count = 0
    for cell in code_cells:
        outputs = cell.get("outputs", [])
        if any(o.get("output_type") == "error" for o in outputs):
            # Execution errors are the executor's job to report, not ours.
            continue
        text = _output_text(outputs)
        non_error_outputs = [o for o in outputs if o.get("output_type") != "error"]
        is_short_skip = _SKIP_RE.search(text) and len(text.strip()) <= SKIP_MAX_OUTPUT_CHARS
        if is_short_skip:
            skipped_count += 1
        elif non_error_outputs:
            # Produced substantial output (even if it incidentally mentions "skip").
            executed_count += 1
        # else: produced no output at all — counts as neither (in every mode: an
        # artifact lesson's non-running reference cells must not be penalized).

    code_n = len(code_cells)
    reasons: list[str] = []

    if lesson_mode == "executable":
        # All-silent lesson: ≥2 code cells, none produced output, and none even
        # printed a skip message (that case is the skip-fraction rule below). The
        # learner never sees anything work. Single trivial cells are not flagged.
        if code_n >= 2 and executed_count == 0 and skipped_count == 0:
            reasons.append(
                "no code cell produced real output — the lesson never demonstrates anything"
            )
        if code_n >= 2 and skipped_count / code_n >= SKIP_FRACTION_THRESHOLD:
            reasons.append(
                f"{skipped_count} of {code_n} code cells were skipped "
                "(e.g. missing prerequisites), so the core demonstration never ran"
            )
    elif lesson_mode == "artifact":
        # The deliverable is a file/config/scaffold: hollow unless at least one
        # code cell actually built-and-validated it for real. Reference cells that
        # never ran are not skips here — they simply don't count toward the bar.
        if executed_count == 0:
            reasons.append(
                "no code cell actually built or validated an artifact with real "
                "output — the lesson never demonstrates a working deliverable"
            )
    # lesson_mode == "conceptual": no code is expected, so the code-based checks
    # never fire — the verdict rests solely on the prose/section check below.

    if section_count < MIN_SECTIONS and markdown_word_count < MIN_MARKDOWN_WORDS:
        reasons.append(
            "almost no explanatory content (too few sections and too little prose)"
        )

    return StructuralReport(
        is_hollow=bool(reasons),
        reasons=tuple(reasons),
        section_count=section_count,
        code_cell_count=code_n,
        executed_count=executed_count,
        skipped_count=skipped_count,
        markdown_word_count=markdown_word_count,
    )
