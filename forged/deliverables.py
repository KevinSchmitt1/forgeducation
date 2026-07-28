"""Per-run deliverable writers, shared by the single-lesson CLI path and the
curriculum orchestrator.

These turn a terminal ``PipelineState`` + its ``ArtifactStore`` into the files a
learner actually opens: ``SUMMARY.md`` (routing log + honest signals),
``lesson.ipynb`` (the executed notebook), and the self-contained learner package
(``README.md`` + ``requirements.txt``). They live here — not in ``forged.cli`` —
so the orchestrator can call them without a module-load cycle (cli depends on the
curriculum layer, so the curriculum layer must not import cli).

Every writer is best-effort about packaging but authoritative about the notebook:
a degraded run still ships an openable ``lesson.ipynb`` and a usable README.
"""

from __future__ import annotations

from pathlib import Path

# What each lesson mode's verification actually checked, for the honest SUMMARY
# statement (docs/architecture/17-lesson-modes.md). Keyed by LessonMode's literal
# values rather than the type itself, so this stays a plain module constant.
_MODE_VERIFICATION_NOTE: dict[str, str] = {
    "executable": "Cells were executed and checked for real output.",
    "artifact": "Artifacts were built and validated by cells that ran for real.",
    "conceptual": (
        "**No code was executed** — this lesson is prose/diagrams only; "
        "explanations were not checked against execution."
    ),
}


def write_agentic_summary(run_dir: Path, state, elapsed_sec: float) -> None:
    """Write SUMMARY.md with routing log for agentic pipeline."""
    from .pipeline.mode import DEFAULT_MODE, extract_lesson_mode

    if state.is_terminal and state.terminal_ok:
        status = "✓ Acceptable"
    elif state.is_terminal:
        status = "✗ Ended without an acceptable notebook"
    else:
        status = "✗ Incomplete"

    lesson_mode = extract_lesson_mode(_read_latest_plan_text(run_dir, state))

    lines = ["# Agentic Pipeline Summary\n\n"]
    lines.append(f"**Status**: {status}\n")
    if state.terminal_reason:
        lines.append(f"**Reason**: {state.terminal_reason}\n")
    lines.append(f"**Elapsed**: {elapsed_sec:.1f} seconds\n")
    lines.append(f"**Iterations**: {state.iteration}\n\n")

    lines.append("## Lesson Mode\n\n")
    lines.append(f"**Mode**: {lesson_mode}\n\n")
    lines.append(_MODE_VERIFICATION_NOTE.get(lesson_mode, _MODE_VERIFICATION_NOTE[DEFAULT_MODE]))
    lines.append("\n\n")

    if state.degradations:
        lines.append("## Degradations\n\n")
        lines.append(
            "These stages fell back instead of producing real output — treat the "
            "result with suspicion:\n\n"
        )
        for deg in state.degradations:
            lines.append(f"- **{deg.stage.value}** ({deg.kind}): {deg.detail}\n")
        lines.append("\n")

    # Topic fidelity: surface any capability the topic asked for but the notebook no
    # longer covers, so a descope is reported, never silent (R1, doc 11).
    dropped = [s for s in state.topic_fidelity if s.missing]
    if dropped:
        missing = sorted({cap for s in dropped for cap in s.missing})
        lines.append("## Topic Fidelity\n\n")
        lines.append(
            "The notebook no longer covers every capability the topic requested. "
            "These were dropped during the run:\n\n"
        )
        for cap in missing:
            lines.append(f"- {cap}\n")
        lines.append("\n")

    if state.routing_log:
        lines.append("## Routing Log\n\n")
        for decision in state.routing_log:
            lines.append(f"### Iteration {decision.iteration}\n")
            lines.append(f"- **From**: {decision.from_stage.value}\n")
            lines.append(f"- **To**: {decision.to_stage.value if decision.to_stage else 'END'}\n")
            lines.append(f"- **Classification**: {decision.classification}\n")
            lines.append(f"- **Reason**: {decision.reason}\n\n")

    (run_dir / "SUMMARY.md").write_text("".join(lines), encoding="utf-8")


def _read_latest_plan_text(run_dir: Path, state) -> str:
    """Read the planner's latest lesson-plan markdown straight from the run dir.

    write_agentic_summary only receives run_dir + state (no ArtifactStore), but
    every artifact the store produces during a real run is also persisted to disk
    as it's written (see ArtifactStore.put), so the plan file is guaranteed to be
    there for a real pipeline run. Returns "" when no planner output is recorded
    or its file is missing (e.g. a state built directly in a test) —
    extract_lesson_mode treats an empty string as the conservative default.
    """
    from .pipeline.state import PipelineStage

    for output in reversed(state.outputs):
        if output.stage == PipelineStage.PLANNER:
            plan_path = run_dir / f"{output.artifact_name}.md"
            if plan_path.is_file():
                return plan_path.read_text(encoding="utf-8")
            break
    return ""


def write_final_notebook(run_dir: Path, store, state) -> None:
    """Write the deliverable lesson.ipynb.

    Preference order:
      1. The executed copy of the latest notebook (real cell outputs baked in),
         written by the executor as <execution_report>_executed.ipynb.
      2. The latest assembled (unexecuted) notebook from the CodeAuthor.
      3. An empty-but-valid notebook, so the file is always openable in Jupyter.
    """
    import nbformat

    from .pipeline.state import PipelineStage

    for output in reversed(state.outputs):
        if output.stage == PipelineStage.EXECUTOR:
            executed = run_dir / f"{output.artifact_name}_executed.ipynb"
            if executed.is_file():
                (run_dir / "lesson.ipynb").write_text(
                    executed.read_text(encoding="utf-8"), encoding="utf-8"
                )
                return
            break

    for output in reversed(state.outputs):
        if output.stage in (PipelineStage.CODE_AUTHOR, PipelineStage.CONTENT_REVISER):
            notebook_content = store.get(output.artifact_name).content
            (run_dir / "lesson.ipynb").write_text(notebook_content, encoding="utf-8")
            return

    empty = nbformat.writes(nbformat.v4.new_notebook())
    (run_dir / "lesson.ipynb").write_text(empty, encoding="utf-8")


def write_learner_package(run_dir: Path, store, state, topic: str, learner_profile) -> None:
    """Write the self-contained deliverable (README.md + requirements.txt) from the
    latest lesson plan, so even a degraded agentic run ships something a learner can
    set up and open — not just a notebook (P6). Best-effort: never fail the run over
    packaging; a missing/unparseable plan still yields a usable README + empty deps."""
    import logging

    from .packaging import PackageContext, write_package
    from .pipeline.state import PipelineStage

    plan = ""
    for output in reversed(state.outputs):
        if output.stage == PipelineStage.PLANNER and store.has(output.artifact_name):
            plan = store.get(output.artifact_name).content
            break

    try:
        write_package(
            run_dir,
            plan,
            PackageContext(
                topic=topic,
                learner_name=learner_profile.name,
                learner_description=learner_profile.description,
            ),
        )
    except OSError as exc:
        logging.getLogger(__name__).warning("Failed to write learner package: %s", exc)
