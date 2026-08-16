"""Replacing named cells instead of regenerating the notebook (doc 21, C5).

`code_author` rewrote 24, 21, 24 and 26 cells to repair 8, 1, 3 and 7 — 43% of the
2026-08-13 run's tokens. It did that because the previous notebook was never one of its
inputs, so a fresh notebook from the plan was the only thing it could produce.

These cover the merge primitive: a patch names cells by the SAME index the executor
reports (verified 1:1 on the corpus), and every untouched cell must survive byte-for-byte
— a patch that quietly reflows the rest of the notebook would destroy the very thing that
makes patching cheaper than rewriting.
"""

from __future__ import annotations

import json

import nbformat
import pytest

from forged.notebook import apply_patch, build_notebook, cells_from_json, patch_from_json

BASE_CELLS = [
    {"type": "markdown", "source": "# Start Here\n\nWhat this lesson does."},
    {"type": "code", "source": "import json\nprint('setup ok')"},
    {"type": "markdown", "source": "## Build the artifact"},
    {"type": "code", "source": "broken = '''unterminated"},
]


def _notebook() -> str:
    return build_notebook(BASE_CELLS)


def _sources(notebook_json: str) -> list[str]:
    return [c.source for c in nbformat.reads(notebook_json, as_version=4).cells]


# ── apply_patch ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_replaces_only_the_named_cell() -> None:
    before = _sources(_notebook())

    after = _sources(apply_patch(_notebook(), [{"index": 3, "type": "code", "source": "ok = 1"}]))

    assert after[3] == "ok = 1"
    assert after[:3] == before[:3], "untouched cells must survive byte-for-byte"
    assert len(after) == len(before), "a replace-only patch never changes the cell count"


@pytest.mark.unit
def test_replaces_several_cells_in_one_patch() -> None:
    patch = [
        {"index": 1, "type": "code", "source": "a = 1"},
        {"index": 3, "type": "code", "source": "b = 2"},
    ]

    after = _sources(apply_patch(_notebook(), patch))

    assert after[1] == "a = 1"
    assert after[3] == "b = 2"
    assert after[0] == BASE_CELLS[0]["source"]


@pytest.mark.unit
def test_a_cell_can_change_type() -> None:
    """A code cell that should have been prose is a legitimate repair."""
    result = apply_patch(_notebook(), [{"index": 3, "type": "markdown", "source": "just prose"}])

    cells = nbformat.reads(result, as_version=4).cells
    assert cells[3].cell_type == "markdown"


@pytest.mark.unit
def test_the_result_is_a_valid_notebook() -> None:
    result = apply_patch(_notebook(), [{"index": 0, "type": "markdown", "source": "# New"}])

    nbformat.validate(nbformat.reads(result, as_version=4))


@pytest.mark.unit
@pytest.mark.parametrize(
    "entry",
    [
        {"index": 9, "type": "code", "source": "x"},
        {"index": -1, "type": "code", "source": "x"},
        {"index": "3", "type": "code", "source": "x"},
        {"index": True, "type": "code", "source": "x"},
        {"index": 1, "type": "raw", "source": "x"},
        {"index": 1, "type": "code", "source": 42},
        {"index": 1, "type": "code"},
        {"type": "code", "source": "x"},
    ],
)
def test_a_malformed_entry_is_refused(entry: dict) -> None:
    """Half-applying a notebook is worse than failing: the caller degrades honestly."""
    with pytest.raises(ValueError):
        apply_patch(_notebook(), [entry])


@pytest.mark.unit
def test_an_empty_patch_is_refused() -> None:
    with pytest.raises(ValueError):
        apply_patch(_notebook(), [])


@pytest.mark.unit
def test_nothing_is_applied_when_one_entry_is_bad() -> None:
    """Validation happens before mutation — no partial writes."""
    patch = [
        {"index": 1, "type": "code", "source": "good = 1"},
        {"index": 99, "type": "code", "source": "bad"},
    ]

    with pytest.raises(ValueError):
        apply_patch(_notebook(), patch)


# ── patch_from_json ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_reads_a_patch_response() -> None:
    raw = json.dumps({"patch": [{"index": 2, "type": "code", "source": "x = 1"}]})

    assert patch_from_json(raw) == [{"index": 2, "type": "code", "source": "x = 1"}]


@pytest.mark.unit
def test_tolerates_a_json_fence_like_the_cells_parser_does() -> None:
    raw = '```json\n{"patch": [{"index": 0, "type": "code", "source": "x"}]}\n```'

    assert patch_from_json(raw) is not None


@pytest.mark.unit
def test_a_full_notebook_response_is_not_a_patch() -> None:
    """The author keeps the option to rewrite — some repairs cannot be a patch."""
    assert patch_from_json(json.dumps({"cells": BASE_CELLS})) is None
    assert patch_from_json(json.dumps(BASE_CELLS)) is None


@pytest.mark.unit
def test_unparseable_output_is_not_a_patch() -> None:
    assert patch_from_json("not json at all") is None


# ── the existing contract is untouched ────────────────────────────────────────────


@pytest.mark.unit
def test_cells_from_json_still_reads_a_full_notebook() -> None:
    """Regression: the full-rewrite path must behave exactly as before."""
    assert cells_from_json(json.dumps({"cells": BASE_CELLS})) == BASE_CELLS
    assert cells_from_json(json.dumps(BASE_CELLS)) == BASE_CELLS
