"""Tests for the curriculum orchestrator (doc 13, Phase 2).

The orchestrator runs each module through the UNCHANGED run_pipeline, with the context
hand-down: each later module's learner profile gains the earlier modules' objectives as
prior knowledge. These tests stub run_pipeline (async) and the per-module deliverable
writer so the orchestration logic is exercised with no LLM/network/notebook machinery.
"""

from __future__ import annotations

import dataclasses

import pytest

import forged.curriculum.orchestrator as orch
from forged.context import build_context_block, topic_spec_to_json
from forged.curriculum.model import CourseResult, CourseSpec, ModuleSpec
from forged.models import LearnerProfile, TopicSpecification


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


def _module(title: str, objectives: list[str], order: int) -> ModuleSpec:
    return ModuleSpec(
        spec=TopicSpecification(
            title=title,
            scope="implementation",
            learning_objectives=objectives,
            prerequisites=[],
            constraints="",
            depth="intermediate",
            focus_areas=[],
        ),
        order=order,
    )


class _FakeState:
    def __init__(self, terminal_ok: bool = True, topic_fidelity=()) -> None:
        self.is_terminal = True
        self.terminal_ok = terminal_ok
        self.topic_fidelity = topic_fidelity
        self.outputs = ()


@pytest.fixture
def recorder(monkeypatch):
    """Patch run_pipeline + the deliverable writer; record each module's seeded context."""
    calls: list[dict] = []

    async def _stub_run_pipeline(state, store, pipeline, personas_dir, provision=True):
        calls.append(
            {
                "run_id": state.run_id,
                "brief": store.get("brief").content,
                "lesson_context": store.get("lesson_context").content
                if store.has("lesson_context")
                else "",
                "topic_spec": store.get("topic_spec").content,
                "provision": provision,
            }
        )
        return _FakeState()

    def _stub_deliverables(run_dir, store, state, title, profile):
        # Simulate the real writer producing a notebook so notebook_path is set.
        (run_dir / "lesson.ipynb").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(orch, "run_pipeline", _stub_run_pipeline)
    monkeypatch.setattr(orch, "_write_module_deliverables", _stub_deliverables)
    return calls


def _two_module_course() -> CourseSpec:
    return CourseSpec(
        title="Local LLMs",
        modules=(
            _module("Setup the stack", ["install the PyTorch stack"], 0),
            _module("Fine-tune with LoRA", ["fine-tune a model with LoRA"], 1),
        ),
        rationale="split",
    )


@pytest.mark.unit
def test_run_course_creates_one_dir_per_module(recorder, tmp_path) -> None:
    result = orch.run_course(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas",
    )
    assert isinstance(result, CourseResult)
    assert len(result.modules) == 2
    dirs = sorted(p.name for p in (tmp_path / "course").iterdir() if p.is_dir())
    assert dirs[0].startswith("module_0_") and dirs[1].startswith("module_1_")


@pytest.mark.unit
def test_context_handdown_folds_earlier_objectives_into_later_module(recorder, tmp_path) -> None:
    orch.run_course(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas",
    )
    # Module 1's context must mention module 0's objective; module 0's must not mention module 1's.
    assert "install the PyTorch stack" in recorder[1]["lesson_context"]
    assert "fine-tune a model with LoRA" not in recorder[0]["lesson_context"]


@pytest.mark.unit
def test_context_uses_build_context_block_verbatim(recorder, tmp_path) -> None:
    """No divergent context builder: module 0's lesson_context equals build_context_block
    of the (unaugmented) profile + module spec."""
    course = _two_module_course()
    orch.run_course(
        course, _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas",
    )
    expected = build_context_block(_profile(), course.modules[0].spec)
    assert recorder[0]["lesson_context"] == expected


@pytest.mark.unit
def test_base_profile_is_not_mutated(recorder, tmp_path) -> None:
    profile = _profile()
    orch.run_course(
        _two_module_course(), profile, tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas",
    )
    assert profile.prior_knowledge == ["Python"]


@pytest.mark.unit
def test_brief_and_topic_spec_are_per_module(recorder, tmp_path) -> None:
    course = _two_module_course()
    orch.run_course(
        course, _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas",
    )
    assert recorder[0]["brief"] == "Setup the stack"
    assert recorder[1]["topic_spec"] == topic_spec_to_json(course.modules[1].spec)


@pytest.mark.unit
def test_failing_module_is_recorded_not_skipped(monkeypatch, tmp_path) -> None:
    async def _flaky(state, store, pipeline, personas_dir, provision=True):
        if "module_1" in state.run_id:
            raise RuntimeError("boom")
        return _FakeState()

    monkeypatch.setattr(orch, "run_pipeline", _flaky)
    monkeypatch.setattr(orch, "_write_module_deliverables", lambda *a, **k: None)

    course = CourseSpec(
        title="C",
        modules=(_module("A", ["a"], 0), _module("B", ["b"], 1), _module("C", ["c"], 2)),
        rationale="",
    )
    result = orch.run_course(
        course, _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas",
    )
    assert len(result.modules) == 3
    assert result.modules[1].terminal_ok is False
    assert result.modules[1].notebook_path is None
    assert result.modules[2].terminal_ok is True  # loop continued past the failure


@pytest.mark.unit
def test_max_modules_caps_the_run(recorder, tmp_path) -> None:
    course = CourseSpec(
        title="C",
        modules=tuple(_module(f"M{i}", [f"o{i}"], i) for i in range(5)),
        rationale="",
    )
    result = orch.run_course(
        course, _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas", max_modules=2,
    )
    assert len(result.modules) == 2
    assert len(recorder) == 2


@pytest.mark.unit
def test_no_provision_is_threaded_through(recorder, tmp_path) -> None:
    orch.run_course(
        _two_module_course(), _profile(), tmp_path / "course",
        pipeline=object(), personas_dir=tmp_path / "personas", provision=False,
    )
    assert all(call["provision"] is False for call in recorder)


@pytest.mark.unit
def test_topic_fidelity_signals_captured(monkeypatch, tmp_path) -> None:
    from forged.pipeline.state import TopicFidelitySignal

    signal = TopicFidelitySignal(
        requested_capabilities=("train",), covered=(), missing=("train",), source="deterministic"
    )

    async def _stub(state, store, pipeline, personas_dir, provision=True):
        return _FakeState(topic_fidelity=(signal,))

    monkeypatch.setattr(orch, "run_pipeline", _stub)
    monkeypatch.setattr(orch, "_write_module_deliverables", lambda *a, **k: None)

    result = orch.run_course(
        CourseSpec(title="C", modules=(_module("A", ["a"], 0),), rationale=""),
        _profile(), tmp_path / "course", pipeline=object(), personas_dir=tmp_path / "p",
    )
    assert result.modules[0].topic_fidelity == (signal,)


@pytest.mark.unit
def test_augment_profile_is_immutable_and_appends(  ) -> None:
    profile = _profile()  # prior_knowledge == ["Python"]
    completed = (_module("Setup", ["install stack"], 0),)
    augmented = orch._augment_profile(profile, completed)
    assert augmented.prior_knowledge == ["Python", "install stack"]
    assert profile.prior_knowledge == ["Python"]  # original untouched
    assert augmented is not profile


@pytest.mark.unit
def test_augment_profile_uses_dataclasses_replace_semantics() -> None:
    """Sanity: the helper returns a LearnerProfile differing only in prior_knowledge."""
    profile = _profile()
    augmented = orch._augment_profile(profile, ())
    assert dataclasses.replace(augmented, prior_knowledge=["Python"]) == profile
