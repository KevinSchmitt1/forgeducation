"""Tests for deterministic plan operations (doc 16, Phase 1).

These are pure functions the front-door gate applies to a frozen `CourseSpec` when the
learner asks for a structural tweak ("merge these", "drop that", "one notebook", "swap").
No LLM writes the new plan — the operations derive it. Every operation must:

- never mutate its input (frozen objects + no shared lists),
- renumber surviving modules 0..N-1 in their new order,
- remap `module_prerequisites` (references by title) to surviving/merged titles, or drop
  a reference whose module was removed.
"""

from __future__ import annotations

import dataclasses

import pytest

from forged.curriculum.model import CourseSpec, ModuleSpec
from forged.curriculum.operations import (
    drop_module,
    force_single,
    merge_modules,
    reorder_modules,
)
from forged.models import TopicSpecification


def _topic(title: str, objectives: list[str], focus: list[str]) -> TopicSpecification:
    return TopicSpecification(
        title=title,
        scope="implementation",
        learning_objectives=objectives,
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=focus,
    )


def _module(
    title: str,
    order: int,
    objectives: list[str] | None = None,
    focus: list[str] | None = None,
    prereqs: tuple[str, ...] = (),
) -> ModuleSpec:
    return ModuleSpec(
        spec=_topic(title, objectives or [f"{title} obj"], focus or []),
        order=order,
        module_prerequisites=prereqs,
    )


def _course(*modules: ModuleSpec) -> CourseSpec:
    return CourseSpec(title="Local LLMs", modules=modules, rationale="split")


def _three_module_course() -> CourseSpec:
    """[0] Setup ← []   [1] Train ← [Setup]   [2] Serve ← [Train]"""
    return _course(
        _module("Setup", 0, ["install stack"], ["device choice"]),
        _module("Train", 1, ["fine-tune with LoRA"], ["LoRA adapters"], ("Setup",)),
        _module("Serve", 2, ["serve the model"], ["inference"], ("Train",)),
    )


# ── T1.1 merge_modules ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_merge_reduces_count_and_renumbers() -> None:
    merged = merge_modules(_three_module_course(), 0, 1)
    assert len(merged.modules) == 2
    assert tuple(m.order for m in merged.modules) == (0, 1)


@pytest.mark.unit
def test_merge_joins_titles_and_combines_capabilities_deduped() -> None:
    course = _course(
        _module("Setup", 0, ["install stack"], ["device choice"]),
        _module("Train", 1, ["fine-tune", "install stack"], ["device choice"]),
    )
    merged = merge_modules(course, 0, 1)
    m0 = merged.modules[0]
    assert m0.spec.title == "Setup + Train"
    # order-preserving, de-duplicated union
    assert m0.spec.learning_objectives == ["install stack", "fine-tune"]
    assert m0.spec.focus_areas == ["device choice"]


@pytest.mark.unit
def test_merge_remaps_later_prerequisite_reference_to_merged_title() -> None:
    # Merge Setup+Train; Serve depended on "Train" → now depends on "Setup + Train".
    merged = merge_modules(_three_module_course(), 0, 1)
    serve = merged.modules[1]
    assert serve.spec.title == "Serve"
    assert serve.module_prerequisites == ("Setup + Train",)


@pytest.mark.unit
def test_merge_drops_self_reference_between_the_two_merged_modules() -> None:
    # Train depends on Setup; merging them must not leave a self-referential prereq.
    merged = merge_modules(_three_module_course(), 0, 1)
    assert merged.modules[0].module_prerequisites == ()


@pytest.mark.unit
def test_merge_accepts_targets_in_either_order() -> None:
    a = merge_modules(_three_module_course(), 0, 1)
    b = merge_modules(_three_module_course(), 1, 0)
    assert a.modules[0].spec.title == b.modules[0].spec.title == "Setup + Train"


@pytest.mark.unit
def test_merge_same_index_raises() -> None:
    with pytest.raises(ValueError):
        merge_modules(_three_module_course(), 1, 1)


# ── T1.2 drop_module ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_drop_reduces_count_and_renumbers() -> None:
    course, _dropped = drop_module(_three_module_course(), 1)
    assert tuple(m.spec.title for m in course.modules) == ("Setup", "Serve")
    assert tuple(m.order for m in course.modules) == (0, 1)


@pytest.mark.unit
def test_drop_returns_dropped_capabilities() -> None:
    _course_after, dropped = drop_module(_three_module_course(), 1)
    assert dropped == ("fine-tune with LoRA", "LoRA adapters")


@pytest.mark.unit
def test_drop_strips_dangling_prerequisite_references() -> None:
    # Serve depended on Train; dropping Train must strip that dangling reference.
    course, _dropped = drop_module(_three_module_course(), 1)
    serve = course.modules[1]
    assert serve.module_prerequisites == ()


# ── T1.3 force_single ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_force_single_collapses_to_one_module() -> None:
    single = force_single(_three_module_course())
    assert len(single.modules) == 1
    assert single.modules[0].order == 0
    assert single.modules[0].module_prerequisites == ()


@pytest.mark.unit
def test_force_single_unions_capabilities_and_joins_titles() -> None:
    single = force_single(_three_module_course())
    m0 = single.modules[0]
    assert m0.spec.title == "Setup + Train + Serve"
    assert m0.spec.learning_objectives == [
        "install stack",
        "fine-tune with LoRA",
        "serve the model",
    ]
    assert m0.spec.focus_areas == ["device choice", "LoRA adapters", "inference"]


@pytest.mark.unit
def test_force_single_on_one_module_returns_it_unchanged() -> None:
    course = _course(_module("Setup", 0))
    assert force_single(course) is course


# ── T1.4 reorder_modules ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_reorder_valid_permutation_renumbers() -> None:
    # Swap the last two of an independent course (no prereqs).
    course = _course(
        _module("A", 0), _module("B", 1), _module("C", 2)
    )
    reordered = reorder_modules(course, (0, 2, 1))
    assert tuple(m.spec.title for m in reordered.modules) == ("A", "C", "B")
    assert tuple(m.order for m in reordered.modules) == (0, 1, 2)


@pytest.mark.unit
def test_reorder_placing_module_before_prerequisite_raises() -> None:
    # Train builds on Setup; ordering Train before Setup is invalid.
    with pytest.raises(ValueError, match="Train.*Setup|Setup.*Train"):
        reorder_modules(_three_module_course(), (1, 0, 2))


@pytest.mark.unit
def test_reorder_non_permutation_wrong_length_raises() -> None:
    with pytest.raises(ValueError):
        reorder_modules(_three_module_course(), (0, 1))


@pytest.mark.unit
def test_reorder_non_permutation_duplicate_raises() -> None:
    with pytest.raises(ValueError):
        reorder_modules(_three_module_course(), (0, 0, 1))


# ── T1.5 immutability + edge cases ────────────────────────────────────────────────


@pytest.mark.unit
def test_operations_do_not_mutate_input_course() -> None:
    course = _three_module_course()
    before = dataclasses.asdict(course)
    merge_modules(course, 0, 1)
    drop_module(course, 2)
    force_single(course)
    reorder_modules(_course(_module("A", 0), _module("B", 1)), (1, 0))
    assert dataclasses.asdict(course) == before


@pytest.mark.unit
@pytest.mark.parametrize("bad", [3, -1, 99])
def test_merge_out_of_range_raises_with_range_in_message(bad: int) -> None:
    with pytest.raises(ValueError, match="0.*2|range"):
        merge_modules(_three_module_course(), 0, bad)


@pytest.mark.unit
@pytest.mark.parametrize("bad", [3, -1, 99])
def test_drop_out_of_range_raises_with_range_in_message(bad: int) -> None:
    with pytest.raises(ValueError, match="0.*2|range"):
        drop_module(_three_module_course(), bad)
