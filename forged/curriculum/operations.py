"""Deterministic plan operations for the smart front door (doc 16, Phase 1).

Module-level pure functions the interactive gate applies to a frozen `CourseSpec` when
the learner asks for a structural tweak. They live here — *not* on the model — so
`model.py` stays a dumb value object and the front door owns the editing vocabulary.

Every operation:
- returns a **new** `CourseSpec` (never mutates its input; no shared lists),
- renumbers surviving modules `0..N-1` in their new order,
- remaps `module_prerequisites` (references to other modules *by title*) to the
  surviving/merged title, and drops a reference whose module was removed.

Module targets are the displayed positions, which equal `order` (the model keeps modules
renumbered `0..N-1`). Out-of-range or malformed targets raise `ValueError` with the valid
range in the message.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Sequence
from typing import cast

from forged.pipeline.mode import LessonMode

from .model import CourseSpec, ModuleSpec

# ── Helpers ────────────────────────────────────────────────────────────────────────


def _dedup(items: Iterable[str]) -> list[str]:
    """Order-preserving de-duplication into a fresh list."""
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


def _validate_index(course: CourseSpec, index: int) -> None:
    """Raise ValueError naming the valid range if `index` is out of bounds."""
    count = len(course.modules)
    if index < 0 or index >= count:
        raise ValueError(
            f"module index {index} out of range (valid range 0..{count - 1})"
        )


# Mode strictness, most executable first. A merged module inherits both parts'
# deliverables, so it needs the mode whose rigor covers both (doc 18, Phase 3):
# `executable` demands a computed result, `artifact` a built-and-validated file,
# `conceptual` neither.
_MODE_STRICTNESS: dict[str, int] = {"conceptual": 0, "artifact": 1, "executable": 2}


def _merge_modes(modes: Iterable[LessonMode | None]) -> LessonMode | None:
    """The mode a module merged from `modes` should carry.

    Returns the most executable of them. `None` (undecided) propagates: merging must
    never invent a decision nobody made — the lesson planner still infers that case.
    """
    collected = list(modes)
    if any(mode is None for mode in collected):
        return None
    return max(collected, key=lambda mode: _MODE_STRICTNESS[str(mode)])


def _renumber(modules: Sequence[ModuleSpec]) -> tuple[ModuleSpec, ...]:
    """Return a new tuple of modules with `order` set to their position 0..N-1."""
    return tuple(
        dataclasses.replace(module, order=position)
        for position, module in enumerate(modules)
    )


def _remap_prerequisites(
    module: ModuleSpec, rename: dict[str, str], drop: set[str]
) -> ModuleSpec:
    """Rewrite a module's `module_prerequisites`: rename mapped titles, drop removed
    ones, de-duplicate, and never let a module list itself as a prerequisite."""
    remapped: list[str] = []
    for prereq in module.module_prerequisites:
        if prereq in drop:
            continue
        renamed = rename.get(prereq, prereq)
        if renamed == module.spec.title:
            continue
        remapped.append(renamed)
    new_prereqs = tuple(_dedup(remapped))
    if new_prereqs == module.module_prerequisites:
        return module
    return dataclasses.replace(module, module_prerequisites=new_prereqs)


# ── Operations ─────────────────────────────────────────────────────────────────────


def merge_modules(course: CourseSpec, first: int, second: int) -> CourseSpec:
    """Merge two modules into one lesson at the earlier position.

    The merged module joins titles ("A + B"), concatenates learning objectives, focus
    areas, and prerequisites (each de-duplicated, order-preserving), and inherits the
    earlier module's scope/depth/constraints. Later modules that referenced either old
    title now reference the merged title.
    """
    _validate_index(course, first)
    _validate_index(course, second)
    if first == second:
        raise ValueError("cannot merge a module with itself")

    lo, hi = sorted((first, second))
    early, late = course.modules[lo], course.modules[hi]
    merged_title = f"{early.spec.title} + {late.spec.title}"

    merged_spec = dataclasses.replace(
        early.spec,
        title=merged_title,
        learning_objectives=_dedup(
            [*early.spec.learning_objectives, *late.spec.learning_objectives]
        ),
        focus_areas=_dedup([*early.spec.focus_areas, *late.spec.focus_areas]),
        prerequisites=_dedup([*early.spec.prerequisites, *late.spec.prerequisites]),
    )
    old_titles = {early.spec.title, late.spec.title}
    merged_module = ModuleSpec(
        spec=merged_spec,
        order=lo,
        module_prerequisites=tuple(
            _dedup(
                p
                for p in (*early.module_prerequisites, *late.module_prerequisites)
                if p not in old_titles
            )
        ),
        lesson_mode=_merge_modes((early.lesson_mode, late.lesson_mode)),
    )

    rename = {early.spec.title: merged_title, late.spec.title: merged_title}
    rebuilt: list[ModuleSpec] = []
    for position, module in enumerate(course.modules):
        if position == lo:
            rebuilt.append(merged_module)
        elif position == hi:
            continue
        else:
            rebuilt.append(_remap_prerequisites(module, rename, drop=set()))

    return dataclasses.replace(course, modules=_renumber(rebuilt))


def drop_module(course: CourseSpec, target: int) -> tuple[CourseSpec, tuple[str, ...]]:
    """Remove a module. Returns the new course and the dropped module's capabilities
    so the caller can warn the learner about exactly what they gave up."""
    _validate_index(course, target)
    removed = course.modules[target]
    dropped_capabilities = removed.capabilities

    survivors = [m for position, m in enumerate(course.modules) if position != target]
    rebuilt = [
        _remap_prerequisites(m, rename={}, drop={removed.spec.title}) for m in survivors
    ]
    new_course = dataclasses.replace(course, modules=_renumber(rebuilt))
    return new_course, dropped_capabilities


def force_single(course: CourseSpec) -> CourseSpec:
    """Collapse every module into one lesson (merge-all-and-warn).

    A single-module course is returned unchanged. Otherwise the union of all objectives
    and focus areas is folded into the first module's spec, titles are joined with " + ",
    and there are no inter-module prerequisites left to carry.
    """
    if len(course.modules) <= 1:
        return course

    base = course.modules[0]
    joined_title = " + ".join(m.spec.title for m in course.modules)
    single_spec = dataclasses.replace(
        base.spec,
        title=joined_title,
        learning_objectives=_dedup(
            obj for m in course.modules for obj in m.spec.learning_objectives
        ),
        focus_areas=_dedup(
            area for m in course.modules for area in m.spec.focus_areas
        ),
        prerequisites=_dedup(
            pre for m in course.modules for pre in m.spec.prerequisites
        ),
    )
    single_module = ModuleSpec(
        spec=single_spec,
        order=0,
        module_prerequisites=(),
        lesson_mode=_merge_modes(m.lesson_mode for m in course.modules),
    )
    return dataclasses.replace(course, modules=(single_module,))


def set_mode(course: CourseSpec, target: int, mode: str) -> CourseSpec:
    """Set one module's lesson mode, leaving every other module untouched.

    The operator's override at the plan gate (doc 18, D3). Unlike the structural ops this
    changes nothing about ordering or capabilities — only how the module will be taught —
    so no renumbering or prerequisite remapping is needed.

    Raises ValueError for an out-of-range module or an unrecognized mode word; the gate
    turns both into a re-prompt rather than a crash.
    """
    _validate_index(course, target)
    if mode not in _MODE_STRICTNESS:
        known = ", ".join(sorted(_MODE_STRICTNESS))
        raise ValueError(f"unknown lesson mode {mode!r}; expected one of: {known}")
    validated = cast(LessonMode, mode)

    rebuilt = tuple(
        dataclasses.replace(module, lesson_mode=validated) if position == target else module
        for position, module in enumerate(course.modules)
    )
    return dataclasses.replace(course, modules=rebuilt)


def reorder_modules(course: CourseSpec, new_order: tuple[int, ...]) -> CourseSpec:
    """Reorder modules by a full permutation of the current indices.

    `new_order` lists the current indices in their desired new sequence, e.g. `(0, 2, 1)`
    keeps module 0 first, then old module 2, then old module 1. Raises ValueError if
    `new_order` is not a permutation, or if it would place a module before a module it
    lists as a prerequisite.
    """
    count = len(course.modules)
    if sorted(new_order) != list(range(count)):
        raise ValueError(
            f"reorder needs a full permutation of 0..{count - 1}, got {new_order!r}"
        )

    sequenced = [course.modules[i] for i in new_order]
    position_of_title = {m.spec.title: pos for pos, m in enumerate(sequenced)}
    for position, module in enumerate(sequenced):
        for prereq in module.module_prerequisites:
            prereq_position = position_of_title.get(prereq)
            if prereq_position is not None and prereq_position >= position:
                raise ValueError(
                    f"cannot place '{module.spec.title}' before its prerequisite "
                    f"'{prereq}'"
                )

    return dataclasses.replace(course, modules=_renumber(sequenced))
