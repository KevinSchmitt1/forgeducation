"""Unit tests for the deterministic dependency extractor.

No LLM, no network — these feed lesson-plan markdown to extract_requirements()
and assert the normalized requirement set, its pip-renderable text, and the
stable content-addressed hash that Phase 5's venv cache will key on.

Run with:
    pytest tests/pipeline/test_dependencies.py -v
"""

from __future__ import annotations

import pytest

from forged.pipeline.dependencies import (
    Requirement,
    RequirementSet,
    extract_requirements,
    normalize_name,
)

# ── normalize_name (PEP 503) ────────────────────────────────────────────────────


def test_normalize_name_lowercases_and_unifies_separators():
    assert normalize_name("Flask_SQLAlchemy") == "flask-sqlalchemy"
    assert normalize_name("huggingface_hub") == "huggingface-hub"
    assert normalize_name("ruamel.yaml") == "ruamel-yaml"
    assert normalize_name("  NumPy  ") == "numpy"


# ── Structured `requirements` block (primary path) ──────────────────────────────


_STRUCTURED_PLAN = """## Prerequisites
Some prose about conda and hardware.

```requirements
numpy>=1.26
matplotlib>=3.8
pandas
```

## Learning objectives
- do things
"""


def test_extracts_structured_block_in_order_with_specifiers():
    result = extract_requirements(_STRUCTURED_PLAN)
    assert result.source == "structured"
    assert result.requirements == (
        Requirement(name="numpy", specifier=">=1.26"),
        Requirement(name="matplotlib", specifier=">=3.8"),
        Requirement(name="pandas", specifier=""),
    )


def test_structured_block_ignores_comments_and_blank_lines():
    plan = "```requirements\n# core deps\nnumpy>=1.26\n\n  \npandas\n```\n"
    result = extract_requirements(plan)
    assert [r.name for r in result.requirements] == ["numpy", "pandas"]


def test_structured_block_normalizes_names_and_dedupes_keeping_specifier():
    plan = "```requirements\nHuggingFace_Hub\nhuggingface-hub>=0.20\n```\n"
    result = extract_requirements(plan)
    # One entry, normalized, and the specifier-bearing duplicate wins.
    assert result.requirements == (Requirement(name="huggingface-hub", specifier=">=0.20"),)


def test_structured_block_parses_extras_and_compound_specifiers():
    plan = "```requirements\nuvicorn[standard]>=0.20\ntorch>=2.0,<3.0\n```\n"
    result = extract_requirements(plan)
    assert result.requirements == (
        Requirement(name="uvicorn", specifier="[standard]>=0.20"),
        Requirement(name="torch", specifier=">=2.0,<3.0"),
    )


def test_empty_structured_block_yields_no_requirements_but_is_structured():
    plan = "## Prerequisites\nNo packages needed.\n```requirements\n```\n"
    result = extract_requirements(plan)
    assert result.requirements == ()
    assert result.source == "structured"


# ── Prose fallback (no structured block) ────────────────────────────────────────


def test_falls_back_to_pip_install_lines_when_no_block():
    plan = """## Prerequisites
Install Hugging Face and helpers:
   - pip install transformers>=4.30 datasets>=2.12 accelerate>=0.20 huggingface_hub
"""
    result = extract_requirements(plan)
    assert result.source == "prose"
    assert {r.name for r in result.requirements} == {
        "transformers",
        "datasets",
        "accelerate",
        "huggingface-hub",
    }


def test_prose_fallback_handles_python_m_pip_and_drops_flags():
    plan = "Setup: python -m pip install --upgrade rich==13.7 typer\n"
    result = extract_requirements(plan)
    assert {r.name for r in result.requirements} == {"rich", "typer"}
    assert result.requirement_for("rich").specifier == "==13.7"


def test_prose_fallback_ignores_sentence_embedded_pip_install_decoys():
    # Real localLLM plan: a genuine install line plus a prose sentence that happens to
    # contain "pip install". Only the real packages should survive — no "the"/"packages".
    plan = """## Prerequisites
   - pip install transformers>=4.30 datasets>=2.12 huggingface_hub sentencepiece

If you must use pip-only, follow the PyTorch docs then pip install the HF packages above.
"""
    result = extract_requirements(plan)
    assert {r.name for r in result.requirements} == {
        "transformers",
        "datasets",
        "huggingface-hub",
        "sentencepiece",
    }


def test_no_requirements_anywhere_is_empty_with_none_source():
    plan = "## Prerequisites\nJust use the Python standard library.\n"
    result = extract_requirements(plan)
    assert result.requirements == ()
    assert result.source == "none"


def test_structured_block_takes_precedence_over_prose_pip_lines():
    plan = """## Prerequisites
pip install legacy-from-prose>=1.0

```requirements
chosen-from-block>=2.0
```
"""
    result = extract_requirements(plan)
    assert result.source == "structured"
    assert [r.name for r in result.requirements] == ["chosen-from-block"]


# ── Rendering ───────────────────────────────────────────────────────────────────


def test_render_txt_is_sorted_and_pip_parseable():
    plan = "```requirements\npandas\nnumpy>=1.26\n```\n"
    text = extract_requirements(plan).render_txt()
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert lines == ["numpy>=1.26", "pandas"]  # alphabetical


def test_render_txt_empty_set_has_only_a_comment():
    text = RequirementSet(requirements=(), source="none").render_txt()
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert lines == []
    assert text.startswith("#")  # explanatory comment, still pip-parseable


# ── Stable content-addressed hash ───────────────────────────────────────────────


def test_hash_is_stable_and_order_independent():
    a = extract_requirements("```requirements\nnumpy>=1.26\npandas\n```\n")
    b = extract_requirements("```requirements\npandas\nnumpy>=1.26\n```\n")
    assert a.requirements_hash == b.requirements_hash
    assert len(a.requirements_hash) == 64  # sha256 hex


def test_hash_changes_when_a_specifier_changes():
    a = extract_requirements("```requirements\nnumpy>=1.26\n```\n")
    b = extract_requirements("```requirements\nnumpy>=2.0\n```\n")
    assert a.requirements_hash != b.requirements_hash


def test_empty_set_hash_is_deterministic():
    a = RequirementSet(requirements=(), source="none")
    b = RequirementSet(requirements=(), source="structured")
    # Hash is over content only, independent of how the empty set was derived.
    assert a.requirements_hash == b.requirements_hash


# ── Edge cases ──────────────────────────────────────────────────────────────────


def test_requirement_for_raises_when_name_absent():
    result = extract_requirements("```requirements\nnumpy>=1.26\n```\n")
    with pytest.raises(KeyError):
        result.requirement_for("pandas")


def test_non_package_tokens_in_block_are_dropped():
    # URLs / VCS refs are not plain name[extras][specifier] tokens — ignored, not guessed.
    plan = "```requirements\ngit+https://example.com/pkg.git\nnumpy>=1.26\n```\n"
    result = extract_requirements(plan)
    assert [r.name for r in result.requirements] == ["numpy"]
