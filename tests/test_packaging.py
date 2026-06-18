"""Unit tests for the self-contained deliverable packaging.

write_package() turns a finished run dir into something a learner can actually use:
a pip-parseable requirements.txt and a learner-facing README.md, both derived
deterministically from the lesson plan. No LLM, no network.

Run with:
    pytest tests/test_packaging.py -v
"""

from __future__ import annotations

import nbformat

from forged.packaging import (
    README_FILE,
    REQUIREMENTS_FILE,
    PackageContext,
    build_readme,
    write_package,
)

_PLAN = """## Assumed knowledge
- Python basics.

## Prerequisites
Install the packages below.

```requirements
numpy>=1.26
matplotlib>=3.8
```

## Learning objectives
- Compute a moving average over a series.
- Plot the smoothed result.

## Concept sequence
1. Windows.
"""

_CTX = PackageContext(
    topic="Moving averages in NumPy",
    learner_name="Kevin",
    learner_description="Junior DS moving into AI; prefers hands-on examples.",
)


# ── write_package: files on disk ────────────────────────────────────────────────


def test_write_package_creates_both_files(tmp_path):
    result = write_package(tmp_path, _PLAN, _CTX)
    assert set(result.filenames) == {README_FILE, REQUIREMENTS_FILE}
    assert (tmp_path / README_FILE).is_file()
    assert (tmp_path / REQUIREMENTS_FILE).is_file()


def test_requirements_file_is_pip_parseable_and_sorted(tmp_path):
    write_package(tmp_path, _PLAN, _CTX)
    lines = [
        ln
        for ln in (tmp_path / REQUIREMENTS_FILE).read_text().splitlines()
        if ln and not ln.startswith("#")
    ]
    # Lesson imports come first, sorted; ipykernel is appended so a fresh learner
    # venv can register itself as a selectable Jupyter kernel.
    assert lines[:2] == ["matplotlib>=3.8", "numpy>=1.26"]
    assert "ipykernel>=6" in lines


def test_requirements_always_include_ipykernel_even_with_no_deps(tmp_path):
    plan = "## Prerequisites\nStandard library only.\n## Learning objectives\n- Learn.\n"
    write_package(tmp_path, plan, _CTX)
    req_text = (tmp_path / REQUIREMENTS_FILE).read_text()
    # The deliverable is a notebook, so ipykernel is needed even when nothing else is.
    assert "ipykernel" in req_text.lower()


def test_write_package_exposes_requirement_set_for_hashing(tmp_path):
    result = write_package(tmp_path, _PLAN, _CTX)
    assert result.requirement_set.source == "structured"
    assert len(result.requirement_set.requirements_hash) == 64


def test_write_package_with_no_deps_still_writes_both_files(tmp_path):
    plan = "## Prerequisites\nStandard library only.\n## Learning objectives\n- Learn.\n"
    result = write_package(tmp_path, plan, _CTX)
    assert set(result.filenames) == {README_FILE, REQUIREMENTS_FILE}
    req_text = (tmp_path / REQUIREMENTS_FILE).read_text()
    assert "no third-party packages" in req_text.lower()


# ── build_readme: content ───────────────────────────────────────────────────────


def test_readme_includes_topic_learner_and_objectives():
    from forged.pipeline.dependencies import extract_requirements

    readme = build_readme(_PLAN, _CTX, extract_requirements(_PLAN))
    assert "Moving averages in NumPy" in readme
    assert "Kevin" in readme
    assert "Junior DS" in readme
    # Objectives from the plan are surfaced as "what this teaches".
    assert "moving average" in readme.lower()


def test_readme_explains_how_to_install_and_run():
    from forged.pipeline.dependencies import extract_requirements

    readme = build_readme(_PLAN, _CTX, extract_requirements(_PLAN))
    assert "pip install -r requirements.txt" in readme
    assert "lesson.ipynb" in readme


def test_readme_explains_kernel_registration_and_recovery():
    """The README must tell the learner how to register AND select the kernel, and
    how to recover when it doesn't show up — the exact gap a learner hits otherwise."""
    from forged.pipeline.dependencies import extract_requirements

    readme = build_readme(_PLAN, _CTX, extract_requirements(_PLAN))
    assert "ipykernel install" in readme
    assert "select" in readme.lower() and "kernel" in readme.lower()
    # The reload-to-rescan recovery path is documented.
    assert "rescan" in readme.lower() or "Reload Window" in readme


def test_readme_carries_prerequisites_prose_but_not_the_fenced_block():
    from forged.pipeline.dependencies import extract_requirements

    readme = build_readme(_PLAN, _CTX, extract_requirements(_PLAN))
    assert "Install the packages below." in readme
    # The machine-readable block belongs in requirements.txt, not the prose README.
    assert "```requirements" not in readme


def test_readme_handles_plan_missing_sections_gracefully():
    from forged.pipeline.dependencies import extract_requirements

    plan = "Just a sentence, no headings."
    readme = build_readme(plan, _CTX, extract_requirements(plan))
    # Still a usable document: topic title + run instructions present.
    assert _CTX.topic in readme
    assert "lesson.ipynb" in readme


# ── Integration: alongside a real notebook ──────────────────────────────────────


def test_package_coexists_with_a_written_notebook(tmp_path):
    (tmp_path / "lesson.ipynb").write_text(nbformat.writes(nbformat.v4.new_notebook()))
    write_package(tmp_path, _PLAN, _CTX)
    assert {p.name for p in tmp_path.iterdir()} >= {
        "lesson.ipynb",
        README_FILE,
        REQUIREMENTS_FILE,
    }
