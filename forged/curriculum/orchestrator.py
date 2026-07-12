"""Curriculum orchestrator (doc 13, Phase 2): run a CourseSpec as N module lessons.

The orchestrator is a pure composition layer ABOVE the unchanged lesson loop. For each
module, in order, it:
  1. builds an augmented LearnerProfile — earlier modules' learning objectives folded
     into prior_knowledge, so a later module is never re-taught earlier material
     (Design decision 7); the base profile is never mutated;
  2. seeds the module's ArtifactStore with `brief`/`lesson_context`/`topic_spec` using the
     SAME builders the single-run path uses (`build_context_block`, `topic_spec_to_json`) —
     no divergent context builder;
  3. runs the module through the UNCHANGED `run_pipeline`;
  4. writes the module's deliverables and records a frozen `ModuleResult`.

A failing module is recorded (terminal_ok=False), never silently skipped. Execution is
sequential (doc 13 Part I.b); the marked loop is where dependency-aware parallelism would
later hook in.

`_write_module_deliverables` reuses the per-run writers in `forged.deliverables`, the same
shared module the single-lesson CLI path uses.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from pathlib import Path
from typing import Any

from forged.artifacts import Artifact, ArtifactStore
from forged.context import build_context_block, topic_spec_to_json
from forged.deliverables import (
    write_agentic_summary,
    write_final_notebook,
    write_learner_package,
)
from forged.models import LearnerProfile
from forged.pipeline.graph import run_pipeline
from forged.pipeline.state import create_initial_state

from .model import CourseResult, CourseSpec, ModuleResult, ModuleSpec

_LOG = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SLUG_MAXLEN = 40


def run_course(
    course: CourseSpec,
    learner_profile: LearnerProfile,
    course_dir: Path,
    *,
    pipeline: Any,
    personas_dir: Path,
    provision: bool = True,
    max_modules: int | None = None,
) -> CourseResult:
    """Run each module of `course` through the lesson pipeline; return a CourseResult.

    Modules run sequentially in order. `max_modules`, when set, caps how many run.
    """
    course_dir.mkdir(parents=True, exist_ok=True)
    modules = course.modules if max_modules is None else course.modules[:max_modules]

    results: list[ModuleResult] = []
    # Sequential execution (doc 13 Part I.b). Dependency-aware parallelism would replace
    # this loop with one bounded asyncio.gather per DAG level; nothing else changes.
    for module in modules:
        completed = tuple(m for m in course.modules if m.order < module.order)
        results.append(
            run_module_with_handdown(
                module, completed, learner_profile, course_dir,
                pipeline=pipeline, personas_dir=personas_dir, provision=provision,
            )
        )
    return CourseResult(course=course, modules=tuple(results))


def run_module_with_handdown(
    module: ModuleSpec,
    completed_modules: tuple[ModuleSpec, ...],
    learner_profile: LearnerProfile,
    course_dir: Path,
    *,
    pipeline: Any,
    personas_dir: Path,
    provision: bool,
) -> ModuleResult:
    """Run one module with the context hand-down (Design decision 7).

    Folds `completed_modules`' objectives into the learner's prior knowledge, builds the
    module's run dir, and runs it through the unchanged pipeline. Shared by the sequential
    course loop and the reactive safety net (doc 13, Phase 4), so both paths seed context
    and record results identically.
    """
    profile = _augment_profile(learner_profile, completed_modules)
    run_dir = _build_module_run_dir(course_dir, module)
    return _run_one_module(module, profile, run_dir, pipeline, personas_dir, provision)


def _augment_profile(
    base_profile: LearnerProfile, completed_modules: tuple[ModuleSpec, ...]
) -> LearnerProfile:
    """Return a new LearnerProfile with earlier modules' objectives folded into
    prior_knowledge. Uses dataclasses.replace + list concatenation — the base profile
    (and its prior_knowledge list) is never mutated."""
    earlier_objectives = [
        obj for module in completed_modules for obj in module.spec.learning_objectives
    ]
    return dataclasses.replace(
        base_profile,
        prior_knowledge=base_profile.prior_knowledge + earlier_objectives,
    )


def _build_module_run_dir(course_dir: Path, module: ModuleSpec) -> Path:
    """<course_dir>/module_<order>_<slug>/ — created on first call, sort-stable by order."""
    run_dir = course_dir / f"module_{module.order}_{_slug(module.spec.title)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _slug(text: str, maxlen: int = _SLUG_MAXLEN) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")[:maxlen] or "module"


def _seed_module_store(
    run_dir: Path, module: ModuleSpec, profile: LearnerProfile
) -> ArtifactStore:
    """Seed the module run's store exactly as the single-run path does (cli._cmd_agentic):
    brief (module title), lesson_context (augmented profile + module spec), topic_spec."""
    store = ArtifactStore(run_dir)
    store.put(Artifact(name="brief", kind="text", content=module.spec.title))
    context = build_context_block(profile, module.spec)
    if context:
        store.put(Artifact(name="lesson_context", kind="text", content=context))
    store.put(
        Artifact(name="topic_spec", kind="json", content=topic_spec_to_json(module.spec))
    )
    return store


def _run_one_module(
    module: ModuleSpec,
    profile: LearnerProfile,
    run_dir: Path,
    pipeline: Any,
    personas_dir: Path,
    provision: bool,
) -> ModuleResult:
    """Run one module through run_pipeline. Never raises: an exception becomes a
    terminal_ok=False result so the course loop continues."""
    store = _seed_module_store(run_dir, module, profile)
    state = create_initial_state(run_id=run_dir.name)
    try:
        final_state = asyncio.run(
            run_pipeline(state, store, pipeline, personas_dir, provision=provision)
        )
    except Exception as exc:  # noqa: BLE001 - record any failure, never abort the course
        _LOG.exception("Course module %s failed: %s", module.order, exc)
        return ModuleResult(
            module=module, run_dir=str(run_dir), terminal_ok=False,
            notebook_path=None, topic_fidelity=(),
        )

    _write_module_deliverables(run_dir, store, final_state, module.spec.title, profile)
    notebook = run_dir / "lesson.ipynb"
    return ModuleResult(
        module=module,
        run_dir=str(run_dir),
        terminal_ok=bool(final_state.is_terminal and final_state.terminal_ok),
        notebook_path=str(notebook) if notebook.is_file() else None,
        topic_fidelity=tuple(final_state.topic_fidelity),
    )


def _write_module_deliverables(
    run_dir: Path, store: ArtifactStore, state: Any, title: str, profile: LearnerProfile
) -> None:
    """Write the module's SUMMARY/notebook/learner-package, reusing the single-run writers
    from `forged.deliverables` (the same shared module the single-lesson CLI path uses)."""
    write_agentic_summary(run_dir, state, 0.0)
    write_final_notebook(run_dir, store, state)
    write_learner_package(run_dir, store, state, title, profile)
