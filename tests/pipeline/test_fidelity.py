"""Unit tests for the deterministic topic-fidelity detector (R1, doc 11).

No LLM, no kernel — these build nbformat notebooks in-memory and assert that
assess_topic_fidelity() reports which requested capabilities the notebook no
longer covers. The detector is a backstop that flips a *silent* topic descope
into a *recorded* one; it is conservative about claiming a capability missing.

Run with:
    pytest tests/pipeline/test_fidelity.py -v
"""

from __future__ import annotations

import nbformat
import pytest

from forged.pipeline.fidelity import TopicFidelityReport, assess_topic_fidelity

# ── Builders ──────────────────────────────────────────────────────────────────


def _nb(markdown: list[str], code: list[str]) -> str:
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [nbformat.v4.new_markdown_cell(m) for m in markdown] + [
        nbformat.v4.new_code_cell(c) for c in code
    ]
    return nbformat.writes(notebook)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_all_capabilities_covered_is_faithful():
    # Arrange — a notebook that both sets up and fine-tunes.
    nb = _nb(
        markdown=["# Setup and fine-tune a local LLM", "## LoRA fine-tuning with peft"],
        code=["model = load_local_llm()", "lora = peft.LoraConfig()\ntrainer.train()"],
    )
    capabilities = ["Set up a local LLM", "Fine-tune the model with LoRA"]

    # Act
    report = assess_topic_fidelity(nb, capabilities)

    # Assert
    assert report.missing == ()
    assert report.is_faithful


@pytest.mark.unit
def test_dropped_capability_is_reported_missing():
    # Arrange — the R1 case: the notebook sets up a model but training is gone.
    # "model"/"local"/"llm" are shared terms; only the distinctive training terms
    # (lora, fine-tune, peft, train) vanish, so the drop must still be caught.
    nb = _nb(
        markdown=["# Set up and run a local LLM", "## Loading and device placement"],
        code=["model = load_local_llm()", "out = model.generate('hello')"],
    )
    capabilities = ["Set up a local LLM", "Fine-tune the model with LoRA"]

    # Act
    report = assess_topic_fidelity(nb, capabilities)

    # Assert
    assert "Fine-tune the model with LoRA" in report.missing
    assert "Set up a local LLM" in report.covered
    assert not report.is_faithful


@pytest.mark.unit
def test_no_capabilities_requested_is_faithful():
    # Arrange / Act — nothing requested means nothing can be dropped.
    report = assess_topic_fidelity(_nb(["# Anything"], ["x = 1"]), [])

    # Assert
    assert report.missing == ()
    assert report.covered == ()
    assert report.is_faithful


@pytest.mark.unit
def test_report_is_immutable():
    report = assess_topic_fidelity(_nb(["# x"], ["y = 1"]), ["Teach x"])
    with pytest.raises((TypeError, AttributeError)):
        report.missing = ()  # type: ignore[misc]


@pytest.mark.unit
def test_requested_equals_covered_plus_missing():
    nb = _nb(["# Setup only"], ["model = setup()"])
    capabilities = ["Set up a local LLM", "Fine-tune with LoRA"]

    report = assess_topic_fidelity(nb, capabilities)

    assert set(report.covered) | set(report.missing) == set(capabilities)
    assert isinstance(report, TopicFidelityReport)
