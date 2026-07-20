"""Course assembly (doc 13, Phase 3): stitch per-module run results into one cohesive
course deliverable.

The orchestrator (Phase 2) and the reactive safety net (Phase 4) each produce a
`CourseResult` — one `ModuleResult` per attempted module. This layer turns that into
what a learner actually navigates:

  - course-root ``README.md`` — an ordered index with prerequisite cross-links,
    reactively-added modules flagged inline.
  - course-root ``COURSE.md`` — **overwrites** the pre-run plan preview
    (`cli._persist_course`) with the post-run outcome: per-module status, notebook
    link, and any still-dropped capabilities.
  - per-module ``NAV.md`` — prev/next/up + prerequisite links. Deliberately not the
    module's own ``README.md`` (that file is already owned by
    `forged.deliverables.write_learner_package`); a separate file avoids coupling
    this layer to a writer it doesn't own.

Always reads `result.course` — the GROWN spec (base modules plus any Phase-4
remediation modules), never the original pre-run plan — so a reactively-added module
is never missing from the deliverable.
"""

from __future__ import annotations

from pathlib import Path

from forged.pipeline.fidelity import TopicFidelityReport

from .model import CourseResult, ModuleResult, ModuleSpec


def assemble_course(
    result: CourseResult,
    course_dir: Path,
    *,
    fidelity: TopicFidelityReport | None = None,
) -> None:
    """Write the course index, the post-run report, and each module's NAV.md.

    `fidelity` is the course-level plan-fidelity verdict (from `assess_course_fidelity`
    at plan time); when given, its verdict is appended to the report. `course_dir` must
    already exist (the orchestrator creates it before any module runs).
    """
    (course_dir / "README.md").write_text(_render_course_index(result), encoding="utf-8")
    (course_dir / "COURSE.md").write_text(
        _render_course_report(result, fidelity), encoding="utf-8"
    )
    _write_module_navs(result)


def _render_course_index(result: CourseResult) -> str:
    """Ordered index of every module in the grown course, one entry per module."""
    course = result.course
    results_by_order = {r.module.order: r for r in result.modules}

    lines = [f"# {course.title}", "", f"_{len(course.modules)} module(s)_", ""]
    for module in course.modules:
        module_result = results_by_order.get(module.order)
        lines.append(f"## [{module.order}] {_index_entry_link(module, module_result)}")
        if module_result is None:
            lines.append("_(not run)_")
        else:
            mark = "✓" if module_result.terminal_ok else "✗"
            lines.append(f"Status: {mark}")
        if module.module_prerequisites:
            lines.append(f"Builds on: {', '.join(module.module_prerequisites)}")
        if module.remediation_for:
            lines.append(
                "_(reactively added — covers: "
                + "; ".join(module.remediation_for)
                + ")_"
            )
        lines.append("")
    return "\n".join(lines)


def _index_entry_link(module: ModuleSpec, module_result: ModuleResult | None) -> str:
    title = module.spec.title
    if module_result is None:
        return title
    dirname = Path(module_result.run_dir).name
    return f"[{title}]({dirname}/README.md)"


def _render_course_report(
    result: CourseResult, fidelity: TopicFidelityReport | None
) -> str:
    """Post-run outcome report: per-module status/notebook/dropped-capability rollup,
    plus an optional plan-fidelity verdict line."""
    ok = sum(1 for m in result.modules if m.terminal_ok)
    total = len(result.modules)
    lines = [
        f"# {result.course.title} — Course Report",
        "",
        f"**Modules:** {ok}/{total} completed",
        "",
    ]

    for module_result in result.modules:
        lines += _render_module_report_section(module_result)

    if fidelity is not None:
        verdict = (
            "✓ covers every requested capability"
            if fidelity.is_faithful
            else "⚠ DROPPED: " + "; ".join(fidelity.missing)
        )
        lines += ["---", "", f"**Plan-fidelity:** {verdict}", ""]

    return "\n".join(lines)


def _render_module_report_section(module_result: ModuleResult) -> list[str]:
    mark = "✓" if module_result.terminal_ok else "✗"
    dirname = Path(module_result.run_dir).name
    section = [f"## {mark} [{module_result.module.order}] {module_result.module.spec.title}", ""]

    if module_result.notebook_path:
        section.append(f"- Notebook: [lesson.ipynb]({dirname}/lesson.ipynb)")
    else:
        section.append("- Notebook: (no notebook)")

    dropped = [cap for signal in module_result.topic_fidelity for cap in signal.missing]
    if dropped:
        section.append(f"- ⚠ still dropped: {'; '.join(dropped)}")
    section.append("")
    return section


def _write_module_navs(result: CourseResult) -> None:
    """Write NAV.md into every module directory that actually ran (Phase 3 uses the
    module's real run_dir — never re-derives a slug, so it can't drift from the
    directory the orchestrator actually created).

    Best-effort like the other per-run writers (`forged.deliverables`): a module
    directory that doesn't exist (the run never got that far) is skipped rather than
    fabricated — this layer composes existing run output, it doesn't create it.
    """
    ordered = sorted(result.modules, key=lambda r: r.module.order)
    dirname_by_title: dict[str, str] = {
        r.module.spec.title: Path(r.run_dir).name for r in ordered
    }

    for i, module_result in enumerate(ordered):
        run_dir = Path(module_result.run_dir)
        if not run_dir.is_dir():
            continue
        prev_result = ordered[i - 1] if i > 0 else None
        next_result = ordered[i + 1] if i + 1 < len(ordered) else None
        nav = _render_module_nav(module_result, prev_result, next_result, dirname_by_title)
        (run_dir / "NAV.md").write_text(nav, encoding="utf-8")


def _render_module_nav(
    module_result: ModuleResult,
    prev_result: ModuleResult | None,
    next_result: ModuleResult | None,
    dirname_by_title: dict[str, str],
) -> str:
    module = module_result.module
    lines = [f"# Navigation — {module.spec.title}", "", "- ↑ [Course index](../README.md)"]

    if prev_result is not None:
        prev_dir = Path(prev_result.run_dir).name
        lines.append(
            f"- ← Previous: [{prev_result.module.spec.title}]({'../' + prev_dir}/README.md)"
        )
    if next_result is not None:
        next_dir = Path(next_result.run_dir).name
        lines.append(
            f"- → Next: [{next_result.module.spec.title}]({'../' + next_dir}/README.md)"
        )
    if module.module_prerequisites:
        links = [
            _prerequisite_link(title, dirname_by_title)
            for title in module.module_prerequisites
        ]
        lines.append(f"- Builds on: {', '.join(links)}")

    return "\n".join(lines) + "\n"


def _prerequisite_link(title: str, dirname_by_title: dict[str, str]) -> str:
    dirname = dirname_by_title.get(title)
    if dirname is None:
        return title  # prerequisite module didn't run — name it honestly, no dead link
    return f"[{title}](../{dirname}/README.md)"
