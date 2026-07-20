"""Course data model: a course is an ordered set of module specs.

Each `ModuleSpec` wraps a `TopicSpecification`, so a module run is an ordinary agentic
run (maximal reuse of the single-lesson pipeline). The course adds only ordering,
inter-module prerequisites, and course metadata. Everything is frozen — same
immutability discipline as `PipelineState`.

A module's "capabilities" are its `learning_objectives + focus_areas`, mirroring R1's
derivation in `reviser._assess_topic_fidelity`, so the course-level fidelity check
(`forged.curriculum.fidelity`) agrees with the per-module R1 detector.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from forged.models import TopicSpecification
from forged.pipeline.state import TopicFidelitySignal


def topic_capabilities(spec: TopicSpecification) -> tuple[str, ...]:
    """The capabilities a topic spec requests: objectives + focus areas.

    Mirrors the derivation in `forged.pipeline.agents.reviser._assess_topic_fidelity`
    so the course-level union check and the per-module R1 detector judge the same set.
    Blank entries are dropped.
    """
    return tuple(
        c for c in (*spec.learning_objectives, *spec.focus_areas) if c and c.strip()
    )


@dataclass(frozen=True)
class ModuleSpec:
    """One module of a course — an ordinary topic plus its place in the sequence.

    `module_prerequisites` names earlier modules (by title) this one builds on; the
    orchestrator folds those modules' objectives into the learner's prior knowledge so
    a later module never re-teaches an earlier one (doc 13, Design decision 7).

    `remediation_for` names the capabilities this module was reactively spawned to
    cover (doc 13, Phase 4's R1 → planner → R1 loop); empty means the module was part
    of the original proactive decomposition. It is coarse-grained by design — the
    whole round's overflow union, not per-module-attributed capability sets — so the
    course assembly (Phase 3) can flag a reactively-added module honestly without
    claiming false precision about which module dropped which capability.
    """

    spec: TopicSpecification
    order: int
    module_prerequisites: tuple[str, ...] = ()
    remediation_for: tuple[str, ...] = ()

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Capabilities this module covers (objectives + focus areas)."""
        return topic_capabilities(self.spec)


@dataclass(frozen=True)
class CourseSpec:
    """An ordered course of module lessons with the rationale for the split.

    `rationale` records *why* this decomposition — both an audit trail and a check on
    the planner's honesty (it must account for every requested capability).
    """

    title: str
    modules: tuple[ModuleSpec, ...]
    rationale: str = ""

    @property
    def all_capabilities(self) -> tuple[str, ...]:
        """Ordered, de-duplicated union of every module's capabilities.

        This union is what the honesty invariant checks against the original topic:
        the course must, collectively, still cover everything the topic requested.
        """
        seen: dict[str, None] = {}
        for module in self.modules:
            for capability in module.capabilities:
                seen.setdefault(capability, None)
        return tuple(seen)


@dataclass(frozen=True)
class ModuleResult:
    """Outcome of running one module through the lesson pipeline.

    `topic_fidelity` carries the R1 signal(s) recorded on the module's final state —
    the trigger the reactive safety net (Phase 4) reads to detect a module that is
    still over-large. `notebook_path` is None when the run failed before producing one.
    """

    module: ModuleSpec
    run_dir: str
    terminal_ok: bool
    notebook_path: str | None
    topic_fidelity: tuple[TopicFidelitySignal, ...]


@dataclass(frozen=True)
class CourseResult:
    """Outcome of a whole course run: one ModuleResult per attempted module, in order."""

    course: CourseSpec
    modules: tuple[ModuleResult, ...]


def course_to_dict(course: CourseSpec) -> dict[str, Any]:
    """Serialize a CourseSpec to a plain JSON-able dict (for `--plan-only` persistence).

    Recurses through the frozen dataclasses, so each module carries its full
    TopicSpecification. Read-only properties (capabilities) are not fields and are
    intentionally omitted — they are derivable from the spec.
    """
    return asdict(course)
