"""A crashed module must explain itself, and an unassessable check must say so.

Both defects were observed on the 2026-07-30 validation run
(`runs/20260730-215250_course_teach_me_how_to_work_with_ai_a`):

1. Module 1 raised inside `run_pipeline`. The orchestrator's `except` path returned
   before `_write_module_deliverables`, so no SUMMARY.md and no FAILED.md were written
   (doc 18's D6 only covered "completed but unacceptable"). Separately, `setup_logging`
   is called only on the single-lesson CLI path, so the course orchestrator's
   `_LOG.exception(...)` went to a logger with no handler. Between them, the module left
   nothing but its seed files and the traceback was destroyed — the run could not be
   diagnosed at all.

2. `COURSE.md` reported `⚠ DROPPED` for the entire raw topic, in that run and the one
   before it. That is an artifact, not drift: with a bare `--topic`, `_default_topic_spec`
   derives two near-identical pseudo-capabilities, and term-coverage cannot assess a
   300-character sentence. Claiming a capability was dropped when nothing was measurably
   checked is exactly the dishonesty this project exists to avoid.
"""

from __future__ import annotations

from pathlib import Path

from forged.curriculum.model import ModuleSpec
from forged.models import LearnerProfile, TopicSpecification


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Kevin",
        description="Junior data scientist.",
        prior_knowledge=["Python"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="",
    )


def _module(title: str = "Project layout") -> ModuleSpec:
    return ModuleSpec(
        spec=TopicSpecification(
            title=title,
            scope="implementation",
            learning_objectives=[f"{title} objective"],
            prerequisites=[],
            constraints="",
            depth="intermediate",
            focus_areas=[],
        ),
        order=0,
    )


# ── A module that raises must leave a diagnosis behind ────────────────────────────


def test_a_crashed_module_writes_a_failure_stub_naming_the_error(monkeypatch, tmp_path):
    # Arrange — make run_pipeline blow up the way module 1 did.
    import forged.curriculum.orchestrator as orch

    def _boom(*args, **kwargs):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(orch, "run_pipeline", _boom)

    # Act
    result = orch._run_one_module(
        _module(), _profile(), tmp_path, pipeline=object(),
        personas_dir=Path("personas"), provision=False,
    )

    # Assert — the module reports failure AND says why, on disk.
    assert result.terminal_ok is False
    stub = tmp_path / "FAILED.md"
    assert stub.is_file(), "a crashed module must not leave the run undiagnosable"
    text = stub.read_text()
    assert "planner exploded" in text
    assert "RuntimeError" in text


def test_a_crashed_module_records_the_traceback_not_just_the_message(monkeypatch, tmp_path):
    # Arrange
    import forged.curriculum.orchestrator as orch

    def _boom(*args, **kwargs):
        raise ValueError("deep failure")

    monkeypatch.setattr(orch, "run_pipeline", _boom)

    # Act
    orch._run_one_module(
        _module(), _profile(), tmp_path, pipeline=object(),
        personas_dir=Path("personas"), provision=False,
    )

    # Assert — a bare message is not enough to debug a pipeline crash.
    text = (tmp_path / "FAILED.md").read_text()
    assert "Traceback" in text
    assert "_boom" in text


def test_a_crashed_module_leaves_a_pipeline_log(monkeypatch, tmp_path):
    """`setup_logging` ran only on the single-lesson path, so course modules had no
    handler and `_LOG.exception(...)` was discarded."""
    # Arrange
    import forged.curriculum.orchestrator as orch

    def _boom(*args, **kwargs):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(orch, "run_pipeline", _boom)

    # Act
    orch._run_one_module(
        _module(), _profile(), tmp_path, pipeline=object(),
        personas_dir=Path("personas"), provision=False,
    )

    # Assert
    log = tmp_path / "pipeline.log"
    assert log.is_file(), "a course module must produce its own pipeline.log"
    assert "planner exploded" in log.read_text()


# ── An unassessable fidelity check must not claim a drop ──────────────────────────


def test_no_requested_capabilities_reports_not_assessed_not_dropped() -> None:
    # Arrange — a bare --topic yields no discrete capabilities to term-match.
    from forged.curriculum.assembler import render_fidelity_verdict
    from forged.pipeline.fidelity import assess_capability_coverage

    report = assess_capability_coverage("anything at all", [])

    # Act
    verdict = render_fidelity_verdict(report, assessed=False)

    # Assert — honest about not having checked, rather than a false ✓ or a false ⚠.
    assert "not assessed" in verdict.lower()
    assert "DROPPED" not in verdict
    assert "✓" not in verdict


def test_a_real_capability_list_still_reports_a_genuine_drop() -> None:
    # Arrange — the check must keep working when there ARE discrete capabilities.
    from forged.curriculum.assembler import render_fidelity_verdict
    from forged.pipeline.fidelity import assess_capability_coverage

    report = assess_capability_coverage(
        "setting up the model environment",
        ["set up the model environment", "train the model with LoRA adapters"],
    )

    # Act
    verdict = render_fidelity_verdict(report, assessed=True)

    # Assert
    assert "DROPPED" in verdict
    assert "LoRA" in verdict


def test_default_topic_spec_no_longer_duplicates_the_topic() -> None:
    """Half the root cause: the raw topic went into BOTH learning_objectives and
    focus_areas. Distinctive terms are computed *among* the requested set, so the pair
    cancelled each other down to the single word "understand" — which no module title
    ever contains, guaranteeing a reported drop."""
    # Arrange / Act
    from forged.cli import _default_topic_spec
    from forged.curriculum.model import topic_capabilities

    caps = topic_capabilities(_default_topic_spec("quantum teleportation"))

    # Assert — one capability, not two restatements of one.
    assert caps == ("Understand quantum teleportation",)


def test_a_short_topic_stays_assessable_so_real_drops_are_still_caught() -> None:
    # Arrange — a one-line topic HAS a distinctive-term signature; keep checking it.
    from forged.cli import _default_topic_spec, _requested_capabilities

    # Act
    caps = _requested_capabilities(_default_topic_spec("quantum teleportation"))

    # Assert
    assert caps == ("Understand quantum teleportation",)


def test_a_paragraph_topic_is_not_assessable() -> None:
    """The other half: term-coverage assumes a capability statement, not a brief. Kevin's
    60-word topic reported DROPPED even against a decomposition that plainly covered it,
    on both 2026-07-28 and 2026-07-30."""
    # Arrange
    from forged.cli import _default_topic_spec, _requested_capabilities

    topic = (
        "Teach me how to work with AI agents: how to build them, build harnesses for "
        "them, and optimize agentic workflows. At the same time, teach me how to optimize "
        "my own workflow with AI and make my AI setup learn together with me — meaning "
        "how I manage all the files and data on my machine, and how the architecture of "
        "that should look."
    )

    # Act
    caps = _requested_capabilities(_default_topic_spec(topic))

    # Assert — nothing measurable was requested, so nothing is claimed either way.
    assert caps == ()


def test_an_explicit_topic_spec_still_produces_capabilities() -> None:
    # Arrange — a user-supplied spec has real, discrete capabilities; keep checking those.
    from forged.curriculum.model import topic_capabilities

    spec = TopicSpecification(
        title="Local LLMs",
        scope="implementation",
        learning_objectives=["set up the runtime", "train a LoRA adapter"],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=["quantization"],
    )

    # Act / Assert
    assert topic_capabilities(spec) == (
        "set up the runtime",
        "train a LoRA adapter",
        "quantization",
    )
