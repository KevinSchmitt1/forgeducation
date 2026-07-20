"""Tests for course assembly (doc 13, Phase 3): stitching per-module run results into
one cohesive course deliverable.

All tests are unit-level against synthetic `CourseResult` fixtures — no LLM, network, or
pipeline machinery. `assemble_course` is the side-effecting entry point; `_render_course_index`
and `_render_course_report` are the pure, directly-testable string builders it calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forged.curriculum import assembler
from forged.curriculum.model import CourseResult, CourseSpec, ModuleResult, ModuleSpec
from forged.models import TopicSpecification
from forged.pipeline.fidelity import TopicFidelityReport
from forged.pipeline.state import TopicFidelitySignal


def _spec(title: str, objective: str) -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=[objective],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[],
    )


def _module(
    title: str,
    order: int,
    prereqs: tuple[str, ...] = (),
    remediation_for: tuple[str, ...] = (),
) -> ModuleSpec:
    return ModuleSpec(
        spec=_spec(title, f"learn {title}"),
        order=order,
        module_prerequisites=prereqs,
        remediation_for=remediation_for,
    )


def _signal(*missing: str) -> TopicFidelitySignal:
    return TopicFidelitySignal(
        requested_capabilities=tuple(missing), covered=(), missing=tuple(missing),
        source="deterministic",
    )


def _result(
    module: ModuleSpec,
    run_dir: Path,
    terminal_ok: bool,
    has_notebook: bool,
    missing: tuple[str, ...] = (),
) -> ModuleResult:
    return ModuleResult(
        module=module,
        run_dir=str(run_dir),
        terminal_ok=terminal_ok,
        notebook_path=str(run_dir / "lesson.ipynb") if has_notebook else None,
        topic_fidelity=(_signal(*missing),) if missing else (),
    )


# ── _render_course_index ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_orders_modules_and_shows_prerequisite_chain(tmp_path: Path) -> None:
    m0 = _module("Setup", 0)
    m1 = _module("Serve", 1, prereqs=("Setup",))
    course = CourseSpec(title="Local LLMs", modules=(m0, m1), rationale="split")
    result = CourseResult(
        course=course,
        modules=(
            _result(m0, tmp_path / "module_0_setup", True, True),
            _result(m1, tmp_path / "module_1_serve", True, True),
        ),
    )

    index = assembler._render_course_index(result)

    assert index.index("Setup") < index.index("Serve")
    assert "Builds on: Setup" in index


@pytest.mark.unit
def test_index_shows_reactive_provenance_only_when_remediation_for_set(tmp_path: Path) -> None:
    m0 = _module("Setup", 0)
    m1 = _module("Fine-tuning", 1, remediation_for=("fine-tune with LoRA",))
    course = CourseSpec(title="Local LLMs", modules=(m0, m1), rationale="split")
    result = CourseResult(
        course=course,
        modules=(
            _result(m0, tmp_path / "module_0_setup", True, True),
            _result(m1, tmp_path / "module_1_finetune", True, True),
        ),
    )

    index = assembler._render_course_index(result)

    setup_section, finetune_section = index.split("Fine-tuning")
    assert "reactively added" not in setup_section.lower()
    assert "reactively added" in index.lower()
    assert "fine-tune with LoRA" in index


@pytest.mark.unit
def test_index_marks_a_module_absent_from_results_as_not_run(tmp_path: Path) -> None:
    """The assembler reads the GROWN `result.course` — a module present in the spec but
    with no matching ModuleResult (e.g. a --max-modules cutoff) must still appear,
    marked honestly, never silently dropped from the index."""
    m0 = _module("Setup", 0)
    m1 = _module("Serve", 1)
    course = CourseSpec(title="Local LLMs", modules=(m0, m1), rationale="split")
    result = CourseResult(
        course=course,
        modules=(_result(m0, tmp_path / "module_0_setup", True, True),),  # m1 never ran
    )

    index = assembler._render_course_index(result)

    assert "Serve" in index
    assert "not run" in index.lower()


# ── _render_course_report ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_report_shows_terminal_ok_vs_failed_marks(tmp_path: Path) -> None:
    m0 = _module("Setup", 0)
    m1 = _module("Serve", 1)
    course = CourseSpec(title="Local LLMs", modules=(m0, m1), rationale="")
    result = CourseResult(
        course=course,
        modules=(
            _result(m0, tmp_path / "module_0_setup", True, True),
            _result(m1, tmp_path / "module_1_serve", False, False),
        ),
    )

    report = assembler._render_course_report(result, fidelity=None)

    assert "✓" in report
    assert "✗" in report


@pytest.mark.unit
def test_report_surfaces_dropped_capabilities(tmp_path: Path) -> None:
    m0 = _module("Serve", 0)
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    result = CourseResult(
        course=course,
        modules=(
            _result(
                m0, tmp_path / "module_0_serve", False, False,
                missing=("serve over gRPC",),
            ),
        ),
    )

    report = assembler._render_course_report(result, fidelity=None)

    assert "serve over gRPC" in report


@pytest.mark.unit
def test_report_notebook_link_present_when_module_has_a_notebook(tmp_path: Path) -> None:
    m0 = _module("Setup", 0)
    run_dir = tmp_path / "module_0_setup"
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    result = CourseResult(course=course, modules=(_result(m0, run_dir, True, True),))

    report = assembler._render_course_report(result, fidelity=None)

    assert "lesson.ipynb" in report


@pytest.mark.unit
def test_report_notebook_link_absent_when_module_has_no_notebook(tmp_path: Path) -> None:
    m0 = _module("Setup", 0)
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    result = CourseResult(
        course=course,
        modules=(_result(m0, tmp_path / "module_0_setup", False, False),),
    )

    report = assembler._render_course_report(result, fidelity=None)

    assert "lesson.ipynb" not in report
    assert "no notebook" in report.lower()


@pytest.mark.unit
def test_report_plan_fidelity_verdict_gated_on_optional_fidelity_arg(tmp_path: Path) -> None:
    m0 = _module("Setup", 0)
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    result = CourseResult(
        course=course, modules=(_result(m0, tmp_path / "module_0_setup", True, True),)
    )

    without_fidelity = assembler._render_course_report(result, fidelity=None)
    assert "plan-fidelity" not in without_fidelity.lower()

    faithful = TopicFidelityReport(covered=("x",), missing=())
    with_fidelity = assembler._render_course_report(result, fidelity=faithful)
    assert "plan-fidelity" in with_fidelity.lower()
    assert "✓" in with_fidelity

    unfaithful = TopicFidelityReport(covered=(), missing=("y",))
    dropped = assembler._render_course_report(result, fidelity=unfaithful)
    assert "y" in dropped


# ── assemble_course (side-effecting) ────────────────────────────────────────────


@pytest.mark.unit
def test_assemble_course_writes_index_and_report_files(tmp_path: Path) -> None:
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    m0 = _module("Setup", 0)
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    result = CourseResult(
        course=course, modules=(_result(m0, course_dir / "module_0_setup", True, True),)
    )

    assembler.assemble_course(result, course_dir)

    assert (course_dir / "README.md").is_file()
    assert "Setup" in (course_dir / "README.md").read_text()
    assert (course_dir / "COURSE.md").is_file()


@pytest.mark.unit
def test_assemble_course_overwrites_preexisting_course_md(tmp_path: Path) -> None:
    """COURSE.md's pre-run plan preview (written by `_persist_course`) becomes the
    post-run outcome report — it must be overwritten, not appended to."""
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    (course_dir / "COURSE.md").write_text("# stale pre-run preview\n", encoding="utf-8")
    m0 = _module("Setup", 0)
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    result = CourseResult(
        course=course, modules=(_result(m0, course_dir / "module_0_setup", True, True),)
    )

    assembler.assemble_course(result, course_dir)

    content = (course_dir / "COURSE.md").read_text()
    assert "stale pre-run preview" not in content


@pytest.mark.unit
def test_assemble_course_writes_per_module_nav_with_prev_next_up(tmp_path: Path) -> None:
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    m0 = _module("Setup", 0)
    m1 = _module("Serve", 1, prereqs=("Setup",))
    m2 = _module("Fine-tuning", 2, prereqs=("Setup",))
    course = CourseSpec(title="Local LLMs", modules=(m0, m1, m2), rationale="")
    dir0, dir1, dir2 = (
        course_dir / "module_0_setup",
        course_dir / "module_1_serve",
        course_dir / "module_2_finetune",
    )
    for d in (dir0, dir1, dir2):
        d.mkdir()
    result = CourseResult(
        course=course,
        modules=(
            _result(m0, dir0, True, True),
            _result(m1, dir1, True, True),
            _result(m2, dir2, True, True),
        ),
    )

    assembler.assemble_course(result, course_dir)

    nav0 = (dir0 / "NAV.md").read_text()
    nav1 = (dir1 / "NAV.md").read_text()
    nav2 = (dir2 / "NAV.md").read_text()

    # up-link back to the course index
    assert "../README.md" in nav0
    # first module has no previous
    assert "Previous" not in nav0
    assert "module_1_serve" in nav0  # next
    # middle module links both directions
    assert "module_0_setup" in nav1
    assert "module_2_finetune" in nav1
    # last module has no next
    assert "Next" not in nav2
    # prerequisite link resolved to the actual module dir
    assert "module_0_setup" in nav2


@pytest.mark.unit
def test_assemble_course_skips_nav_for_a_module_dir_that_never_ran(tmp_path: Path) -> None:
    """A module result pointing at a directory that doesn't exist (e.g. a fixture's
    placeholder path) must not cause the assembler to fabricate one — it composes
    existing run output, it doesn't create directories."""
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    m0 = _module("Setup", 0)
    course = CourseSpec(title="Local LLMs", modules=(m0,), rationale="")
    missing_dir = tmp_path / "never_created"
    result = CourseResult(course=course, modules=(_result(m0, missing_dir, True, True),))

    assembler.assemble_course(result, course_dir)

    assert not missing_dir.exists()


@pytest.mark.unit
def test_assemble_course_reflects_grown_course_including_reactive_module(
    tmp_path: Path,
) -> None:
    """The grown CourseSpec (post Phase-4) must be what gets assembled, not some
    earlier, smaller plan — every reactively-added module appears in the output."""
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    m0 = _module("Setup", 0)
    m1 = _module("Fine-tuning", 1, remediation_for=("fine-tune with LoRA",))
    grown_course = CourseSpec(
        title="Local LLMs", modules=(m0, m1),
        rationale="base\n\nReactive safety net: added 1 remediation module(s)...",
    )
    result = CourseResult(
        course=grown_course,
        modules=(
            _result(m0, course_dir / "module_0_setup", True, True),
            _result(m1, course_dir / "module_1_finetune", True, True),
        ),
    )

    assembler.assemble_course(result, course_dir)

    readme = (course_dir / "README.md").read_text()
    assert "Fine-tuning" in readme
