"""Curriculum reactive safety net (doc 13, Phase 4): the R1 → planner → R1 loop.

Proactive decomposition (the CurriculumPlanner) is the primary defence against an
over-large topic; this is the backstop. After a course runs, each module carries its R1
topic-fidelity signal. If a module still *dropped* a requested capability (`missing`
non-empty), that overflow is handed back to a remediation planner, which yields a new
module. The new module is appended to the course, run through the UNCHANGED pipeline, and
its own fidelity is re-checked — so the course grows by exactly the overflow, nothing is
silently lost.

The loop is bounded twice so it always terminates:
  - `max_modules` caps the TOTAL number of module runs (base + remediation) — the same
    cost cap the sequential orchestrator honours;
  - `max_depth` caps how many re-decomposition ROUNDS run, so a module that keeps dropping
    cannot loop forever.

It is opt-in (the CLI gates it behind `--redecompose`) and injects the remediation planner
as a callback, so this layer stays LLM-free and unit-testable — the same discipline that
keeps the orchestrator a pure composition layer above `run_pipeline`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forged.models import LearnerProfile, TopicSpecification

from .model import CourseResult, CourseSpec, ModuleResult, ModuleSpec
from .orchestrator import run_course, run_module_with_handdown

_LOG = logging.getLogger(__name__)

# Given the still-dropped capabilities and the learner's (augmented) profile, return zero
# or more topic specs that cover them. The reactive layer assigns each returned spec its
# order + prerequisites — the planner only decides *what* to teach, not *where* it sits.
RemediationPlanner = Callable[[tuple[str, ...], LearnerProfile], tuple[TopicSpecification, ...]]


def run_course_reactive(
    course: CourseSpec,
    learner_profile: LearnerProfile,
    course_dir: Path,
    *,
    pipeline: Any,
    personas_dir: Path,
    plan_remediation: RemediationPlanner,
    provision: bool = True,
    max_modules: int | None = None,
    max_depth: int = 1,
) -> CourseResult:
    """Run `course`, then reactively re-decompose any module that still dropped a capability.

    Returns a CourseResult whose `course` is the grown CourseSpec (base modules + any
    remediation modules appended in order) and whose `modules` includes each remediation
    module's own run result.
    """
    base = run_course(
        course, learner_profile, course_dir,
        pipeline=pipeline, personas_dir=personas_dir,
        provision=provision, max_modules=max_modules,
    )

    all_modules: list[ModuleSpec] = list(course.modules)
    all_results: list[ModuleResult] = list(base.modules)
    pending: list[ModuleResult] = list(base.modules)  # results whose drops we haven't handled

    for _round in range(max_depth):
        dropped = _collect_dropped(pending)
        if not dropped:
            break
        if _budget_exhausted(all_results, max_modules):
            _LOG.info("Reactive loop stopped: max_modules (%s) reached", max_modules)
            break

        profile = _augment_for_remediation(learner_profile, all_modules)
        new_specs = plan_remediation(dropped, profile)
        prerequisites = _dropping_module_titles(pending)

        round_results: list[ModuleResult] = []
        for spec in new_specs:
            if _budget_exhausted(all_results, max_modules):
                break
            module = ModuleSpec(
                spec=spec, order=len(all_modules), module_prerequisites=prerequisites
            )
            result = run_module_with_handdown(
                module, tuple(all_modules), learner_profile, course_dir,
                pipeline=pipeline, personas_dir=personas_dir, provision=provision,
            )
            all_modules.append(module)
            all_results.append(result)
            round_results.append(result)

        if not round_results:
            break  # planner produced nothing runnable — stop cleanly
        pending = round_results  # next round only re-checks what this round produced

    grown = _grow_course(course, all_modules)
    return CourseResult(course=grown, modules=tuple(all_results))


# ── Internals ──────────────────────────────────────────────────────────────────


def _collect_dropped(results: list[ModuleResult]) -> tuple[str, ...]:
    """The de-duplicated union of every capability still `missing` across `results`."""
    seen: dict[str, None] = {}
    for result in results:
        for signal in result.topic_fidelity:
            for capability in signal.missing:
                if capability and capability.strip():
                    seen.setdefault(capability, None)
    return tuple(seen)


def _dropping_module_titles(results: list[ModuleResult]) -> tuple[str, ...]:
    """Titles of the modules in `results` that dropped a capability — the prerequisites a
    remediation module builds on (it teaches the overflow from those lessons)."""
    return tuple(
        dict.fromkeys(
            r.module.spec.title
            for r in results
            if any(sig.missing for sig in r.topic_fidelity)
        )
    )


def _budget_exhausted(results: list[ModuleResult], max_modules: int | None) -> bool:
    return max_modules is not None and len(results) >= max_modules


def _augment_for_remediation(
    learner_profile: LearnerProfile, completed: list[ModuleSpec]
) -> LearnerProfile:
    """The profile handed to the remediation planner: everything run so far is now known,
    so the new module is scoped as follow-on material, not a re-teach."""
    from .orchestrator import _augment_profile

    return _augment_profile(learner_profile, tuple(completed))


def _grow_course(base: CourseSpec, all_modules: list[ModuleSpec]) -> CourseSpec:
    """The base course grown with any appended remediation modules, with an audit note in
    the rationale (doc 13, Phase 4: every re-split is recorded)."""
    added = len(all_modules) - len(base.modules)
    if added <= 0:
        return base
    note = (
        f"\n\nReactive safety net: added {added} remediation module(s) for capabilities a "
        "module run still dropped."
    )
    return CourseSpec(
        title=base.title,
        modules=tuple(all_modules),
        rationale=base.rationale + note,
    )
