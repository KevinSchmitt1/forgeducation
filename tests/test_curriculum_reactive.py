"""Tests for the curriculum reactive safety net (doc 13, Phase 4).

The reactive loop runs a course, then reads each module's R1 topic-fidelity signal: any
`missing` capability is handed back to a remediation planner, which yields a new module
that is run and appended to the grown course. It is bounded by `max_modules` (total run
budget) and `max_depth` (re-decomposition rounds), so it always terminates.

These tests stub `run_pipeline` + the deliverable writer (via the orchestrator module the
reactive layer reuses) and inject a fake remediation planner, so the loop logic is
exercised with no LLM/network/notebook machinery.
"""

from __future__ import annotations

import pytest

import forged.curriculum.orchestrator as orch
import forged.curriculum.reactive as reactive
from forged.curriculum.model import CourseResult, CourseSpec, ModuleSpec
from forged.models import LearnerProfile, TopicSpecification
from forged.pipeline.state import TopicFidelitySignal


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Kevin",
        description="Junior DS moving into AI engineering.",
        prior_knowledge=["Python"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="DS to AI engineering.",
    )


def _spec(title: str, objectives: list[str]) -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=objectives,
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[],
    )


def _module(title: str, objectives: list[str], order: int) -> ModuleSpec:
    return ModuleSpec(spec=_spec(title, objectives), order=order)


def _two_module_course() -> CourseSpec:
    return CourseSpec(
        title="Local LLMs",
        modules=(
            _module("Setup the stack", ["install the PyTorch stack"], 0),
            _module("Serve the model", ["serve the model over HTTP"], 1),
        ),
        rationale="split",
    )


class _FakeState:
    def __init__(self, topic_fidelity=()) -> None:
        self.is_terminal = True
        self.terminal_ok = True
        self.topic_fidelity = topic_fidelity
        self.outputs = ()


def _drop_signal(*missing: str) -> TopicFidelitySignal:
    return TopicFidelitySignal(
        requested_capabilities=tuple(missing),
        covered=(),
        missing=tuple(missing),
        source="deterministic",
    )


@pytest.fixture
def wire(monkeypatch):
    """Patch run_pipeline (keyed on the module's brief) + the deliverable writer.

    Returns a helper that records the seeded context per run and lets a test declare
    which module titles drop which capabilities.
    """
    seen: list[dict] = []

    def _install(drops_by_title: dict[str, tuple[str, ...]] | None = None):
        drops = drops_by_title or {}

        async def _stub_run_pipeline(state, store, pipeline, personas_dir, provision=True):
            title = store.get("brief").content
            seen.append(
                {
                    "title": title,
                    "lesson_context": store.get("lesson_context").content
                    if store.has("lesson_context")
                    else "",
                }
            )
            missing = drops.get(title, ())
            fidelity = (_drop_signal(*missing),) if missing else ()
            return _FakeState(topic_fidelity=fidelity)

        monkeypatch.setattr(orch, "run_pipeline", _stub_run_pipeline)
        monkeypatch.setattr(orch, "_write_module_deliverables", lambda *a, **k: None)
        return seen

    return _install


def _recording_remediation(specs_by_capability: dict[str, TopicSpecification]):
    """A remediation planner that returns one spec per still-dropped capability it knows,
    and records every call for assertions."""
    calls: list[tuple[tuple[str, ...], LearnerProfile]] = []

    def _plan(dropped: tuple[str, ...], profile: LearnerProfile) -> tuple[TopicSpecification, ...]:
        calls.append((dropped, profile))
        return tuple(specs_by_capability[c] for c in dropped if c in specs_by_capability)

    _plan.calls = calls  # type: ignore[attr-defined]
    return _plan


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_drops_returns_base_result_and_never_re_plans(wire, tmp_path) -> None:
    wire()  # no drops
    remediation = _recording_remediation({})
    result = reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation,
    )
    assert isinstance(result, CourseResult)
    assert len(result.modules) == 2
    assert remediation.calls == []  # type: ignore[attr-defined]


@pytest.mark.unit
def test_drop_triggers_a_remediation_module(wire, tmp_path) -> None:
    wire({"Setup the stack": ("fine-tune a model with LoRA",)})
    remediation = _recording_remediation(
        {"fine-tune a model with LoRA": _spec("Fine-tuning", ["fine-tune a model with LoRA"])}
    )
    result = reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation,
    )
    # Two base modules + one remediation module ran and was recorded.
    assert len(result.modules) == 3
    assert result.modules[2].module.spec.title == "Fine-tuning"
    assert result.modules[2].module.order == 2


@pytest.mark.unit
def test_remediation_receives_the_dropped_capabilities(wire, tmp_path) -> None:
    wire({"Setup the stack": ("fine-tune a model with LoRA",)})
    remediation = _recording_remediation(
        {"fine-tune a model with LoRA": _spec("Fine-tuning", ["fine-tune a model with LoRA"])}
    )
    reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation,
    )
    dropped, _profile_arg = remediation.calls[0]  # type: ignore[attr-defined]
    assert dropped == ("fine-tune a model with LoRA",)


@pytest.mark.unit
def test_remediation_module_gets_prior_modules_as_prior_knowledge(wire, tmp_path) -> None:
    seen = wire({"Setup the stack": ("fine-tune a model with LoRA",)})
    remediation = _recording_remediation(
        {"fine-tune a model with LoRA": _spec("Fine-tuning", ["fine-tune a model with LoRA"])}
    )
    reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation,
    )
    # The remediation run (3rd) folds both base modules' objectives into prior knowledge.
    remediation_ctx = seen[2]["lesson_context"]
    assert "install the PyTorch stack" in remediation_ctx
    assert "serve the model over HTTP" in remediation_ctx


@pytest.mark.unit
def test_grown_course_lists_the_remediation_module(wire, tmp_path) -> None:
    wire({"Setup the stack": ("fine-tune a model with LoRA",)})
    remediation = _recording_remediation(
        {"fine-tune a model with LoRA": _spec("Fine-tuning", ["fine-tune a model with LoRA"])}
    )
    result = reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation,
    )
    titles = [m.spec.title for m in result.course.modules]
    assert titles == ["Setup the stack", "Serve the model", "Fine-tuning"]


@pytest.mark.unit
def test_max_depth_bounds_a_self_dropping_remediation(wire, tmp_path) -> None:
    # The remediation module ITSELF keeps dropping — max_depth=1 must stop after one round.
    wire(
        {
            "Setup the stack": ("fine-tune a model with LoRA",),
            "Fine-tuning": ("fine-tune a model with LoRA",),
        }
    )
    remediation = _recording_remediation(
        {"fine-tune a model with LoRA": _spec("Fine-tuning", ["fine-tune a model with LoRA"])}
    )
    result = reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation, max_depth=1,
    )
    assert len(result.modules) == 3  # 2 base + exactly 1 remediation, no runaway
    assert len(remediation.calls) == 1  # type: ignore[attr-defined]


@pytest.mark.unit
def test_max_modules_caps_total_runs_including_remediation(wire, tmp_path) -> None:
    wire({"Setup the stack": ("fine-tune a model with LoRA",)})
    remediation = _recording_remediation(
        {"fine-tune a model with LoRA": _spec("Fine-tuning", ["fine-tune a model with LoRA"])}
    )
    result = reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation, max_modules=2,
    )
    # Budget of 2 is consumed by the base modules — no remediation may run.
    assert len(result.modules) == 2


@pytest.mark.unit
def test_empty_remediation_plan_is_safe(wire, tmp_path) -> None:
    wire({"Setup the stack": ("something unknowable",)})
    remediation = _recording_remediation({})  # returns () for the drop
    result = reactive.run_course_reactive(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "p",
        plan_remediation=remediation,
    )
    assert len(result.modules) == 2  # nothing added; loop terminates cleanly
