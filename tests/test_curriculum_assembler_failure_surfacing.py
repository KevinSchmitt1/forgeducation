"""Tests for course-level failure-reason surfacing (doc 18, D6).

A failed module's `run_dir` carries `FAILED.md` (written by
`forged.deliverables._write_failure_stub` on a hard failure). The assembler reads
that stub's `**Reason**:` line so the course-root `README.md` (index) and
`COURSE.md` (report) can name *why* a module has no notebook, replacing the bare
`✗` — without `ModuleResult` needing a new field and without duplicating
deliverables.py's own reason text.

Unit-level against synthetic `CourseResult` fixtures with a real `FAILED.md`
written to a real tmp_path dir — no LLM, network, or pipeline machinery.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forged.curriculum import assembler
from forged.curriculum.model import CourseResult, CourseSpec, ModuleResult, ModuleSpec
from forged.models import TopicSpecification

_REASON = "Environment provisioning failed: package(s) outside the allow-list: openai"


def _spec(title: str) -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=[f"learn {title}"],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[],
    )


def _module(title: str, order: int) -> ModuleSpec:
    return ModuleSpec(spec=_spec(title), order=order)


def _write_failed_stub(run_dir: Path, reason: str = _REASON) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "FAILED.md").write_text(
        f"# Module failed\n\n**Reason**: {reason}\n\n## Where to look\n\n"
        "- Raw notebook attempts: `lesson_notebook_v*.ipynb`\n"
        "- Full pipeline log: `SUMMARY.md`\n",
        encoding="utf-8",
    )


def _failed_result(module: ModuleSpec, run_dir: Path) -> ModuleResult:
    return ModuleResult(
        module=module, run_dir=str(run_dir), terminal_ok=False,
        notebook_path=None, topic_fidelity=(),
    )


@pytest.mark.unit
def test_index_surfaces_failure_reason_inline_when_failed_md_present(tmp_path: Path) -> None:
    m0 = _module("Building agent harnesses", 0)
    run_dir = tmp_path / "module_0_harnesses"
    _write_failed_stub(run_dir)
    course = CourseSpec(title="AI agents", modules=(m0,), rationale="")
    result = CourseResult(course=course, modules=(_failed_result(m0, run_dir),))

    index = assembler._render_course_index(result)

    assert _REASON in index
    # Not just a bare mark with no context.
    assert "Status: ✗ —" in index or "Status: ✗ -" in index


@pytest.mark.unit
def test_report_surfaces_failure_reason_inline_when_failed_md_present(tmp_path: Path) -> None:
    m0 = _module("Building agent harnesses", 0)
    run_dir = tmp_path / "module_0_harnesses"
    _write_failed_stub(run_dir)
    course = CourseSpec(title="AI agents", modules=(m0,), rationale="")
    result = CourseResult(course=course, modules=(_failed_result(m0, run_dir),))

    report = assembler._render_course_report(result, fidelity=None)

    assert _REASON in report
    assert "FAILED.md" in report


@pytest.mark.unit
def test_index_falls_back_to_bare_mark_when_no_failed_md(tmp_path: Path) -> None:
    """A failed module whose run_dir has no FAILED.md (never got that far, or a
    synthetic ModuleResult) still renders honestly — no fabricated reason text."""
    m0 = _module("Building agent harnesses", 0)
    run_dir = tmp_path / "module_0_harnesses"  # never created
    course = CourseSpec(title="AI agents", modules=(m0,), rationale="")
    result = CourseResult(course=course, modules=(_failed_result(m0, run_dir),))

    index = assembler._render_course_index(result)

    assert "Status: ✗" in index
    assert _REASON not in index


@pytest.mark.unit
def test_assemble_course_writes_reason_bearing_readme_and_course_md(tmp_path: Path) -> None:
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    m0 = _module("Building agent harnesses", 0)
    run_dir = course_dir / "module_0_harnesses"
    _write_failed_stub(run_dir)
    course = CourseSpec(title="AI agents", modules=(m0,), rationale="")
    result = CourseResult(course=course, modules=(_failed_result(m0, run_dir),))

    assembler.assemble_course(result, course_dir)

    readme = (course_dir / "README.md").read_text(encoding="utf-8")
    course_md = (course_dir / "COURSE.md").read_text(encoding="utf-8")
    assert _REASON in readme
    assert _REASON in course_md
