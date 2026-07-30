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


# ── Unfenced `requirements` heading block (secondary structured path) ───────────
#
# The pip-install prose miner is gone (doc 18, D4): it was the sole source of
# fabricated packages and was never the intended contract. A plan that skips the
# fence but still emits a bare `requirements` heading is now parsed directly.


def test_unfenced_heading_block_is_parsed_as_structured():
    plan = """## Prerequisites
Some prose about hardware.

requirements
numpy>=1.26
pandas

## Learning objectives
- do things
"""
    result = extract_requirements(plan)
    assert result.source == "structured"
    assert [r.name for r in result.requirements] == ["numpy", "pandas"]


def test_unfenced_heading_block_accepts_leading_hashes():
    plan = "## requirements\nrich==13.7\ntyper\n\nMore prose.\n"
    result = extract_requirements(plan)
    assert result.source == "structured"
    assert {r.name for r in result.requirements} == {"rich", "typer"}


def test_unfenced_heading_block_stops_at_next_heading_with_no_blank_line():
    plan = "requirements\nnumpy>=1.26\n## Learning objectives\n- foo\n"
    result = extract_requirements(plan)
    assert [r.name for r in result.requirements] == ["numpy"]


def test_unfenced_heading_block_immediately_blank_is_explicit_empty():
    plan = "## Prerequisites\n\nrequirements\n\nNo packages needed for this lesson.\n"
    result = extract_requirements(plan)
    assert result.source == "structured"
    assert result.requirements == ()
    assert result.error is None


def test_fenced_block_takes_precedence_over_unfenced_heading():
    # Belt-and-suspenders: if a plan somehow carries both, the machine-readable fence
    # still wins (mirrors precedence over the old prose miner).
    plan = """requirements
decoy-from-heading>=1.0

```requirements
chosen-from-fence>=2.0
```
"""
    result = extract_requirements(plan)
    assert result.source == "structured"
    assert [r.name for r in result.requirements] == ["chosen-from-fence"]


# ── The real regression: module 3's unfenced block + adjacent decoy prose ───────


def test_real_unfenced_plan_extracts_real_packages_and_never_fabricates_from_prose():
    """Doc 18 / E4: module 3's `lesson_plan_v3.md` fenced `lesson-mode` correctly but
    left `requirements` unfenced. The old fence-only parser missed it entirely and
    fell through to a prose miner that scanned the sentence four lines below —
    `(If you plan to run DVC flows, install dvc separately: `pip install dvc` — not
    required for the core demo.)` — fabricating `not`, `required`, `for`, `the`,
    `core` as "packages" (all four besides `for` are real, live, installable PyPI
    packages: a genuine arbitrary-code-execution vector, not a cosmetic bug).

    With the prose miner removed and the unfenced heading form parsed directly, the
    six real requirements must come back — and none of the fabricated tokens.
    """
    plan = """## Prerequisites
Environment notes:
- CPU-only; small embedding model (all-MiniLM-L6-v2) downloads during run.
- Git initialized in the working directory for optional Git artifact checks
  (GitPython used).
- DVC is optional; the lesson demonstrates a local hashing workflow and shows DVC
  commands as notes. Installing dvc lets learners try real DVC flows.

requirements
sentence-transformers>=2.2.2
faiss-cpu>=1.7.4
scikit-learn>=1.2
numpy>=1.24
GitPython>=3.1
python-dotenv>=1.0

(If you plan to run DVC flows, install dvc separately: `pip install dvc` — not
required for the core demo.)

## Learning objectives
- Design a scalable local project layout for agent projects and validate it
  programmatically.
"""
    result = extract_requirements(plan)
    assert result.source == "structured"
    names = {r.name for r in result.requirements}
    assert names == {
        "sentence-transformers",
        "faiss-cpu",
        "scikit-learn",
        "numpy",
        "gitpython",
        "python-dotenv",
    }
    fabricated = {"not", "required", "for", "the", "core", "dvc"}
    assert names.isdisjoint(fabricated)


# ── Malformed blocks (distinct from "none" and from explicit empty) ─────────────


def test_fenced_block_with_no_parseable_packages_is_malformed():
    plan = "```requirements\ngit+https://example.com/pkg.git only this junk\n```\n"
    result = extract_requirements(plan)
    assert result.source == "malformed"
    assert result.requirements == ()
    assert result.error is not None
    assert "malformed" in result.error.lower()
    # Must read as a parser problem, never as a policy/allow-list violation.
    assert "allow-list" not in result.error.lower()
    assert "policy" not in result.error.lower()


def test_unfenced_heading_block_with_no_parseable_lines_is_malformed():
    plan = "## Prerequisites\n\nrequirements\nnot a real requirement line at all\n\nMore prose.\n"
    result = extract_requirements(plan)
    assert result.source == "malformed"
    assert result.requirements == ()
    assert result.error is not None
    assert "malformed" in result.error.lower()


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


# ── Review follow-ups: silent truncation inside the unfenced heading form ─────────


def test_unfenced_block_keeps_packages_after_a_requirements_txt_comment() -> None:
    """A `# comment` inside the block is a comment, not a terminator.

    `_parse_body` has always skipped `#` lines the way requirements.txt does, but the
    heading scan used to *stop* at the first one — silently dropping every package
    below it, with no error and no `malformed` flag. That is the exact silent-drop
    class doc 18 (D4) exists to eliminate.
    """
    # Arrange
    plan = "requirements\nnumpy\n# core forecasting lib\npandas\n"

    # Act
    result = extract_requirements(plan)

    # Assert
    assert [r.name for r in result.requirements] == ["numpy", "pandas"]
    assert result.source == "structured"


def test_unfenced_block_still_stops_at_the_next_markdown_section() -> None:
    # Arrange — a real `##` heading ends the block; prose below must never be swept in.
    plan = (
        "requirements\nnumpy\n## Learning objectives\n- teach pandas and scikit-learn\n"
    )

    # Act
    result = extract_requirements(plan)

    # Assert
    assert [r.name for r in result.requirements] == ["numpy"]
