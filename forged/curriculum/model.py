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
from typing import Any, get_args

from forged.models import TopicSpecification
from forged.pipeline.mode import LessonMode
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

    `lesson_mode` is the module's *provisional* mode, decided at decomposition time so
    the plan gate can show it and the operator can change it before anything paid runs
    (doc 18, D2/D3). `None` means "undecided here" — the lesson planner infers it as it
    always has, which is what keeps the single-lesson path unchanged. When it is set,
    the lesson planner treats it as binding rather than re-inferring.
    """

    spec: TopicSpecification
    order: int
    module_prerequisites: tuple[str, ...] = ()
    remediation_for: tuple[str, ...] = ()
    lesson_mode: LessonMode | None = None

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


@dataclass(frozen=True)
class ReadinessVerdict:
    """Whether a topic is honestly reachable for THIS learner in one lesson.

    Produced BEFORE any build (pre-execution, LLM) by `forged.curriculum.readiness
    .ReadinessAssessor` — the input-side counterpart to `TopicFidelitySignal`'s
    post-execution drop detection (doc 14, Part III). Deliberately not an extension of
    `TopicFidelitySignal`: that signal is post-execution and deterministic, and doc 11
    pins it "stable and additive-only" as the R1↔curriculum coupling contract —
    overloading it with a pre-execution LLM verdict would blur that seam. Stays outside
    `PipelineState`: a CLI/curriculum-layer value object that never enters the graph.
    """

    reachable: bool
    beachhead: str
    missing_foundations: tuple[str, ...]
    unreachable_capabilities: tuple[str, ...]
    reason: str


def course_to_dict(course: CourseSpec) -> dict[str, Any]:
    """Serialize a CourseSpec to a plain JSON-able dict (for `--plan-only` persistence).

    Recurses through the frozen dataclasses, so each module carries its full
    TopicSpecification. Read-only properties (capabilities) are not fields and are
    intentionally omitted — they are derivable from the spec.
    """
    return asdict(course)


def course_from_dict(data: dict[str, Any]) -> CourseSpec:
    """Reconstruct a frozen CourseSpec from a `course_to_dict` dict — the inverse.

    The round-trip contract holds both ways for any course the pipeline produces:
    ``course_to_dict(course_from_dict(d)) == d`` and
    ``course_from_dict(course_to_dict(c)) == c``. This is what lets a plan cross the
    UI ↔ backend seam as JSON (doc 25) and come back an identical value object.

    `asdict` flattens the frozen tuples (`modules`, `module_prerequisites`,
    `remediation_for`) into lists; this restores them to tuples so equality holds.
    `TopicSpecification`'s own fields stay lists — it is a plain, list-valued dataclass.

    Validates at the boundary — the UI feeds this untrusted JSON — so a missing or
    wrong-typed field raises `ValueError` with a locating message rather than silently
    building a malformed course. Fields absent from an older/partial dict fall back to
    the model's own defaults (`module_prerequisites`/`remediation_for` empty,
    `lesson_mode` None, `rationale` "").
    """
    if not isinstance(data, dict):
        raise ValueError(f"course must be a JSON object, got {type(data).__name__}")

    title = data.get("title")
    if not isinstance(title, str):
        raise ValueError("course 'title' must be a string")

    # `asdict` leaves `modules` a tuple; a JSON round-trip turns it into a list. Accept
    # both so the contract holds whether `d` came straight from `course_to_dict` or from
    # `json.loads` of a persisted plan.
    raw_modules = data.get("modules")
    if not isinstance(raw_modules, (list, tuple)):
        raise ValueError("course 'modules' must be a list")
    modules = tuple(_module_from_dict(m, i) for i, m in enumerate(raw_modules))

    rationale = data.get("rationale", "")
    if not isinstance(rationale, str):
        raise ValueError("course 'rationale' must be a string")

    return CourseSpec(title=title, modules=modules, rationale=rationale)


def _module_from_dict(data: Any, position: int) -> ModuleSpec:
    """Reconstruct one ModuleSpec, naming its position on any validation failure."""
    if not isinstance(data, dict):
        raise ValueError(f"module {position} must be a JSON object")

    order = data.get("order")
    if not isinstance(order, int) or isinstance(order, bool):
        raise ValueError(f"module {position} 'order' must be an integer")

    lesson_mode = data.get("lesson_mode")
    valid_modes = get_args(LessonMode)
    if lesson_mode is not None and lesson_mode not in valid_modes:
        raise ValueError(
            f"module {position} 'lesson_mode' must be null or one of "
            f"{list(valid_modes)}, got {lesson_mode!r}"
        )

    return ModuleSpec(
        spec=_topic_from_dict(data.get("spec"), position),
        order=order,
        module_prerequisites=_str_tuple(
            data.get("module_prerequisites", ()), position, "module_prerequisites"
        ),
        remediation_for=_str_tuple(
            data.get("remediation_for", ()), position, "remediation_for"
        ),
        lesson_mode=lesson_mode,
    )


def _topic_from_dict(data: Any, position: int) -> TopicSpecification:
    """Reconstruct the module's TopicSpecification (a plain, list-valued dataclass)."""
    if not isinstance(data, dict):
        raise ValueError(f"module {position} 'spec' must be a JSON object")
    try:
        return TopicSpecification(
            title=data["title"],
            scope=data["scope"],
            learning_objectives=_str_list(
                data["learning_objectives"], position, "learning_objectives"
            ),
            prerequisites=_str_list(data["prerequisites"], position, "prerequisites"),
            constraints=data["constraints"],
            depth=data["depth"],
            focus_areas=_str_list(data["focus_areas"], position, "focus_areas"),
        )
    except KeyError as exc:
        raise ValueError(f"module {position} 'spec' is missing field {exc}") from None


def _str_list(value: Any, position: int, field: str) -> list[str]:
    """Coerce a JSON array into a list[str], rejecting non-arrays (a bare string would
    otherwise silently iterate into characters)."""
    if not isinstance(value, list):
        raise ValueError(f"module {position} 'spec.{field}' must be a list of strings")
    return [str(item) for item in value]


def _str_tuple(value: Any, position: int, field: str) -> tuple[str, ...]:
    """Like `_str_list` but for the frozen tuple fields on ModuleSpec."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"module {position} '{field}' must be a list of strings")
    return tuple(str(item) for item in value)
