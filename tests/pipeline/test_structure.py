"""Unit tests for the deterministic structural (anti-hollow) assessment.

No LLM, no kernel — these build nbformat notebooks in-memory (with outputs, as
the executor would leave them) and assert assess_structure()'s verdict.

Run with:
    pytest tests/pipeline/test_structure.py -v
"""

from __future__ import annotations

import nbformat
import pytest

from forged.pipeline.structure import StructuralReport, assess_structure

# ── Builders ──────────────────────────────────────────────────────────────────


def _code_cell(source: str, stdout: str | None = None, *, error: bool = False):
    cell = nbformat.v4.new_code_cell(source)
    outputs = []
    if error:
        outputs.append(
            nbformat.v4.new_output("error", ename="ValueError", evalue="boom", traceback=["x"])
        )
    elif stdout is not None:
        outputs.append(nbformat.v4.new_output("stream", name="stdout", text=stdout))
    cell.outputs = outputs
    return cell


def _nb(cells) -> str:
    notebook = nbformat.v4.new_notebook()
    notebook.cells = cells
    return nbformat.writes(notebook)


def _healthy_notebook() -> str:
    """A real lesson: several sections, code cells that actually printed output."""
    return _nb(
        [
            nbformat.v4.new_markdown_cell("# Hash maps\nWhat they are and why they are fast."),
            nbformat.v4.new_markdown_cell("## Building one\nWe insert and look up keys."),
            _code_cell("d = {}\nd['a'] = 1\nprint(d)", stdout="{'a': 1}"),
            nbformat.v4.new_markdown_cell("## Collisions\nHow buckets handle clashes."),
            _code_cell("print(hash('a') % 8)", stdout="3"),
        ]
    )


def _hollow_skipped_notebook() -> str:
    """localLLM-style: a couple of cells run, but the core demo cells all skip."""
    return _nb(
        [
            nbformat.v4.new_markdown_cell("# Fine-tune a small LLM on Apple Silicon"),
            _code_cell("...", stdout="Missing prerequisites detected:\n - torch"),
            _code_cell("...", stdout="Loaded 4 training samples"),
            _code_cell("...", stdout="Baseline generation skipped: missing torch/transformers"),
            _code_cell("...", stdout="Training skipped: missing deps/model/tokenized data."),
            _code_cell("...", stdout="Post-training generation skipped: training did not run."),
        ]
    )


# ── Healthy notebooks are not hollow ──────────────────────────────────────────


@pytest.mark.unit
def test_healthy_notebook_is_not_hollow() -> None:
    report = assess_structure(_healthy_notebook())
    assert report.is_hollow is False
    assert report.reasons == ()
    assert report.executed_count >= 2


@pytest.mark.unit
def test_zero_count_skip_message_is_not_a_skip() -> None:
    """A legitimate '... skipped: 0' report must NOT be counted as a skip.

    False-positive guard: data/ML lessons routinely print cleanup or training
    stats like 'Invalid rows skipped: 0' on cells that did real work.
    """
    nb = _nb(
        [
            nbformat.v4.new_markdown_cell("# Cleaning\nWe drop invalid rows and report counts, "
                                          "explaining each step of the pipeline in real detail."),
            nbformat.v4.new_markdown_cell("## Training\nThen we train and log progress."),
            _code_cell("clean(df)", stdout="Invalid rows skipped: 0\nLoaded 1000 rows"),
            _code_cell("train()", stdout="Skipped 0 batches. Final loss: 0.02"),
        ]
    )
    report = assess_structure(nb)
    assert report.skipped_count == 0
    assert report.executed_count == 2
    assert report.is_hollow is False


@pytest.mark.unit
def test_skip_word_inside_large_real_output_is_not_a_skip() -> None:
    """The word 'skipping' inside a big genuine output does not mark the cell skipped."""
    big = "row " * 100 + "skipping nothing important here"  # > 200 chars of real output
    nb = _nb(
        [
            nbformat.v4.new_markdown_cell("# Lesson\nA real lesson with genuine prose explaining "
                                          "the concept across enough words to pass the check."),
            nbformat.v4.new_markdown_cell("## More\nSecond section of explanation."),
            _code_cell("run()", stdout=big),
            _code_cell("run2()", stdout="result = 42"),
        ]
    )
    report = assess_structure(nb)
    assert report.skipped_count == 0
    assert report.is_hollow is False


@pytest.mark.unit
def test_all_silent_cells_with_no_skips_is_hollow() -> None:
    """Several code cells that print nothing at all (and no skips) → hollow.

    The learner never sees anything work, per the code-author 'must SEE it' rule.
    """
    intro = (
        "# Lesson\nProse that is long enough to clear the "
        "explanation threshold with several real sentences here."
    )
    nb = _nb(
        [
            nbformat.v4.new_markdown_cell(intro),
            nbformat.v4.new_markdown_cell("## Section\nMore prose."),
            _code_cell("x = 1 + 1"),  # no output
            _code_cell("y = x * 2"),  # no output
        ]
    )
    report = assess_structure(nb)
    assert report.executed_count == 0
    assert report.skipped_count == 0
    assert report.is_hollow is True
    assert any("real output" in reason for reason in report.reasons)


# ── The localLLM hollow notebook is caught ────────────────────────────────────


@pytest.mark.unit
def test_localllm_style_hollow_notebook_is_flagged() -> None:
    """Regression guard: a majority-skipped notebook must be flagged hollow.

    This is the exact failure that shipped green from the localLLM run.
    """
    report = assess_structure(_hollow_skipped_notebook())

    assert report.is_hollow is True
    assert report.skipped_count >= 3
    assert any("skipped" in reason for reason in report.reasons)


@pytest.mark.unit
def test_almost_no_explanation_is_hollow() -> None:
    """Too few sections and barely any prose → hollow even if a cell runs."""
    nb = _nb([nbformat.v4.new_markdown_cell("# Hi"), _code_cell("print(1)", stdout="1")])
    report = assess_structure(nb)
    assert report.is_hollow is True
    assert any("explanatory" in reason for reason in report.reasons)


# ── Execution errors are not our concern ──────────────────────────────────────


@pytest.mark.unit
def test_error_cells_do_not_count_as_executed_or_skipped() -> None:
    """A cell that raised is the executor's signal, not the structural gate's."""
    intro = (
        "# Title\nEnough prose to clear the explanation bar here, "
        "describing the concept with several real sentences of text."
    )
    nb = _nb(
        [
            nbformat.v4.new_markdown_cell(intro),
            nbformat.v4.new_markdown_cell("## Section two\nMore explanation to be safe."),
            _code_cell("boom()", error=True),
            _code_cell("print('it works')", stdout="it works"),
        ]
    )
    report = assess_structure(nb)
    assert report.executed_count == 1
    assert report.skipped_count == 0
    assert report.is_hollow is False


# ── Frozen dataclass ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_structural_report_is_immutable() -> None:
    report = StructuralReport(is_hollow=False)
    with pytest.raises((TypeError, AttributeError)):
        report.is_hollow = True  # type: ignore[misc]
