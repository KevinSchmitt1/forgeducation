"""The delimiter-collision detector (doc 20, C1).

An `artifact` lesson that authors a document embeds that document's text in a Python
string literal. When the document is itself about code — an agent instruction file, a
style guide — its examples contain docstrings and fenced blocks, and the first `\"\"\"`
inside the content closes the literal early.

The 2026-08-13 run hit this four times and never escaped, because the revision brief
named the symptom ("SyntaxError ... line 3") and never the mechanism. This detector adds
the mechanism to information we already have.

The four fixtures below are reduced from the real failing cells of
`runs/20260813-201647_create_and_validate__github_co/` (run artifacts are gitignored, so
the shapes are reproduced here rather than referenced):

    v3 cell 7   dedent(\"\"\"...\"\"\") wrapping Markdown containing a docstring  → must fire
    v2 cell 12  same shape, fenced python blocks                              → must fire
    v0 cell 4   ` def _is_git_repo(...)` — one stray leading space            → must NOT fire
    v1 cell 16  subprocess call, parses fine, failed at runtime               → must NOT fire

Precision matters more than recall: a detector that cries collision on every SyntaxError
teaches the code author to ignore it.
"""

from __future__ import annotations

import json

import pytest

from forged.pipeline.diagnosis import (
    cell_has_delimiter_collision,
    diagnose_delimiter_collision,
)

# ── Fixtures reduced from the real failing cells ──────────────────────────────────

COLLIDING_CELL = '''# Artifact: write .github/copilot-instructions.md
from textwrap import dedent

instructions = dedent("""
    # Copilot repository instructions

    Use the project helpers:

    ```python
    def load_config(path: Path) -> Dict[str, Any]:
        """Load configuration from a path using project utilities."""
        return _read(path)
    ```
""")
path.write_text(instructions)
'''

COLLIDING_CELL_NO_FENCE = '''agents_md = """
# AGENTS

Every helper must document itself:

def review(x):
    """Return a verdict for x."""
    return "ok"
"""
'''

STRAY_INDENT_CELL = '''# Choose or bootstrap a git repository to work in
import os, subprocess
from pathlib import Path

 def _is_git_repo(path: Path) -> bool:
    try:
        return (path / ".git").exists()
    except OSError:
        return False
'''

RUNTIME_FAILURE_CELL = '''# Run the validator script
import subprocess, json, sys

proc = subprocess.run([sys.executable, str(validator_path)], capture_output=True)
if "JSON_REPORT=" not in proc.stdout.decode():
    raise SystemExit("Validator did not emit JSON_REPORT=")
'''

HEALTHY_DOCSTRING_CELL = '''def add(a: int, b: int) -> int:
    """Add two numbers and return the result."""
    return a + b


print(add(2, 2))
'''

# The idiom C2 recommends. It is a cell magic, not Python, so ast.parse cannot read it —
# the detector must skip it rather than report the recommended fix as the bug.
WRITEFILE_CELL = """%%writefile AGENTS.md
# Agents

def review(x):
    \"\"\"Return a verdict.\"\"\"

def plan(y):
    \"\"\"Return a plan.\"\"\"
"""

HEALTHY_TEMPLATE_CELL = '''readme = """
# Demo project

A short description with no code examples in it.
"""
path.write_text(readme)
'''


def _notebook(*sources: str) -> str:
    """Minimal nbformat-shaped JSON with the given code cells."""
    return json.dumps(
        {
            "cells": [
                {"cell_type": "code", "source": src, "metadata": {}, "outputs": []}
                for src in sources
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )


# ── The per-cell check ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fires_on_a_literal_whose_content_carries_its_own_delimiter() -> None:
    assert cell_has_delimiter_collision(COLLIDING_CELL) is True


@pytest.mark.unit
def test_fires_without_markdown_fences_too() -> None:
    """The fence is corroborating, not required — a docstring alone closes the literal."""
    assert cell_has_delimiter_collision(COLLIDING_CELL_NO_FENCE) is True


@pytest.mark.unit
def test_does_not_fire_on_a_plain_indentation_slip() -> None:
    assert cell_has_delimiter_collision(STRAY_INDENT_CELL) is False


@pytest.mark.unit
def test_does_not_fire_on_a_cell_that_parses_and_failed_at_runtime() -> None:
    assert cell_has_delimiter_collision(RUNTIME_FAILURE_CELL) is False


@pytest.mark.unit
def test_does_not_fire_on_an_ordinary_docstring() -> None:
    assert cell_has_delimiter_collision(HEALTHY_DOCSTRING_CELL) is False


@pytest.mark.unit
def test_does_not_fire_on_a_well_formed_template_literal() -> None:
    assert cell_has_delimiter_collision(HEALTHY_TEMPLATE_CELL) is False


@pytest.mark.unit
def test_never_fires_on_the_writefile_idiom_it_recommends() -> None:
    """C1 must not report C2's fix as the defect.

    A `%%writefile` cell is IPython cell-magic, not Python: ast.parse always rejects it,
    and its body is arbitrary text that may legitimately contain any number of triple
    quotes. Without this the detector tells the author its correct solution is the bug.
    """
    assert cell_has_delimiter_collision(WRITEFILE_CELL) is False


@pytest.mark.unit
def test_skips_line_magic_and_shell_cells_too() -> None:
    assert cell_has_delimiter_collision("%pip install ruff\n") is False
    assert cell_has_delimiter_collision("!ls -la\n") is False


# ── The notebook-level diagnosis ──────────────────────────────────────────────────


@pytest.mark.unit
def test_names_the_colliding_cells_and_the_mechanism() -> None:
    notebook = _notebook(HEALTHY_DOCSTRING_CELL, COLLIDING_CELL, STRAY_INDENT_CELL)

    message = diagnose_delimiter_collision(notebook, failed_cells=[1, 2])

    assert message is not None
    assert "cell 1" in message
    assert "cell 2" not in message  # the stray indent is a different bug
    assert "%%writefile" in message  # the brief must say what to do instead


@pytest.mark.unit
def test_returns_none_when_no_failed_cell_collides() -> None:
    notebook = _notebook(STRAY_INDENT_CELL, RUNTIME_FAILURE_CELL)

    assert diagnose_delimiter_collision(notebook, failed_cells=[0, 1]) is None


@pytest.mark.unit
def test_only_considers_cells_that_actually_failed() -> None:
    """A colliding cell that did not fail is not this iteration's problem."""
    notebook = _notebook(COLLIDING_CELL, STRAY_INDENT_CELL)

    assert diagnose_delimiter_collision(notebook, failed_cells=[1]) is None


@pytest.mark.unit
def test_reports_several_colliding_cells_together() -> None:
    notebook = _notebook(COLLIDING_CELL, COLLIDING_CELL_NO_FENCE)

    message = diagnose_delimiter_collision(notebook, failed_cells=[0, 1])

    assert message is not None
    assert "cells 0, 1" in message


@pytest.mark.unit
def test_degrades_to_none_on_unparseable_notebook_json() -> None:
    """Diagnosis is a bonus on top of the brief — it must never break the run."""
    assert diagnose_delimiter_collision("{not json", failed_cells=[0]) is None


@pytest.mark.unit
def test_ignores_out_of_range_cell_indices() -> None:
    assert diagnose_delimiter_collision(_notebook(COLLIDING_CELL), failed_cells=[7]) is None


# ── The brief actually carries it ─────────────────────────────────────────────────


@pytest.mark.unit
def test_the_revision_brief_renders_the_diagnosis(tmp_path) -> None:
    """The mechanism must reach code_author, not just be computed."""
    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.failure import (
        Classification,
        ExecutionReport,
        FailureCategory,
    )
    from forged.pipeline.state import PipelineStage

    personas = tmp_path / "personas"
    personas.mkdir()
    (personas / "reviser.md").write_text("You are the Reviser.", encoding="utf-8")

    agent = RevisorAgent(personas_dir=personas)
    brief = agent._synthesize_revision_brief(
        ExecutionReport(ok=False, failed_cells=[7], error_summary="SyntaxError: invalid syntax"),
        None,
        Classification(category=FailureCategory.CODE_QUALITY, reason="Code failed to run."),
        PipelineStage.CODE_AUTHOR,
        diagnosis="**Likely cause — delimiter collision in cell 7.** … use `%%writefile`.",
    )

    assert "delimiter collision in cell 7" in brief
    assert "%%writefile" in brief
    # still reports the symptom it always did
    assert "SyntaxError: invalid syntax" in brief


@pytest.mark.unit
def test_the_brief_is_unchanged_when_there_is_no_diagnosis() -> None:
    """No diagnosis must not alter a brief that previously had none."""
    from pathlib import Path

    from forged.pipeline.agents.reviser import RevisorAgent
    from forged.pipeline.failure import (
        Classification,
        ExecutionReport,
        FailureCategory,
    )
    from forged.pipeline.state import PipelineStage

    agent = RevisorAgent(personas_dir=Path("personas"))
    args = (
        ExecutionReport(ok=False, failed_cells=[4], error_summary="IndentationError"),
        None,
        Classification(category=FailureCategory.CODE_QUALITY, reason="Code failed to run."),
        PipelineStage.CODE_AUTHOR,
    )

    assert agent._synthesize_revision_brief(*args) == agent._synthesize_revision_brief(
        *args, diagnosis=None
    )
