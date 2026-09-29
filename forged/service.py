"""The service layer behind the local UI front door (doc 25, Lane 8).

Four step functions the UI calls, each returning new values and never mutating:

  plan(inputs)                  → plan dict  (CurriculumPlanner + readiness pre-flight)
  preview(plan, inputs)         → PlanPreview (modules, modes, cost, fidelity)
  edit(plan, op, targets)       → EditOutcome (deterministic PlanAdjuster ops, no LLM)
  adjust(plan, sentence, …)     → EditOutcome (PlanAdjuster classify → apply | re-plan)
  build(plan, inputs, …)        → Launch      (the CLI's own `_build_confirmed`, in a
                                               subprocess: `python -m forged.service build`)

Nothing here forks pipeline logic — planning, the gate's step function, the fidelity
check and the build all come from `forged.cli` / `forged.curriculum`. A plan crosses the
UI seam as a `course_to_dict` dict and is re-validated by `course_from_dict` every time.

BYOK: the user's API key is an argument, never state. For in-process planner calls it is
placed in `OPENAI_API_KEY` only for the duration of the call (and the previous value
restored); for the build it is handed to the child process through its environment. It
is never written to disk, never logged, and never part of an LLM prompt or trace payload.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol, get_args, get_type_hints

from forged import cli
from forged.curriculum import adjuster as adjuster_mod
from forged.curriculum import planner as planner_mod
from forged.curriculum import readiness as readiness_mod
from forged.curriculum.adjuster import AdjustmentIntent, PlanAdjuster
from forged.curriculum.fidelity import assess_course_fidelity
from forged.curriculum.gate import (
    _render_estimate,
    _render_fidelity,
    _render_homogeneous_mode_warning,
    apply_adjustment,
    render_plan,
)
from forged.curriculum.model import CourseSpec, course_from_dict, course_to_dict
from forged.curriculum.planner import CurriculumPlanner
from forged.curriculum.readiness import ReadinessAssessor
from forged.models import LearnerProfile, TopicSpecification
from forged.pipeline.mode import LessonMode

API_KEY_ENV = "OPENAI_API_KEY"
REQUEST_VERSION = 1
REQUEST_FILE = "ui_request.json"
LAUNCH_LOG = "ui_launch.log"

# The deterministic edits a UI control can issue directly (no classifier call).
EDIT_OPS = ("merge", "drop", "reorder", "force_single", "set_mode")
LESSON_MODES: tuple[str, ...] = get_args(LessonMode)

# Returns an object with `.complete(system, user, response_format=…)` for a model name.
# None (the default) lets each agent build its real `LLMClient`.
LLMFactory = Callable[[str], Any]

_KEY_LOCK = threading.Lock()


class InputError(ValueError):
    """Invalid UI input; `problems` lists every problem, each naming its field."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


# ── Inputs ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunInputs:
    """What the user authored: the brief plus the two context objects."""

    topic: str
    learner_profile: LearnerProfile
    topic_spec: TopicSpecification


def default_inputs(topic: str = "") -> RunInputs:
    """The CLI's own defaults, so the form starts where `forged learn --topic` does."""
    return RunInputs(
        topic=topic,
        learner_profile=cli._default_learner_profile(),
        topic_spec=cli._default_topic_spec(topic),
    )


def inputs_to_dict(inputs: RunInputs) -> dict[str, Any]:
    return asdict(inputs)


# Read from the models' own Literal annotations, so the dropdowns cannot drift from them.
_PROFILE_HINTS = get_type_hints(LearnerProfile)
_TOPIC_HINTS = get_type_hints(TopicSpecification)
_ENUMS: dict[str, tuple[str, ...]] = {
    **{
        k: get_args(_PROFILE_HINTS[k])
        for k in ("environment", "material_density", "learning_style")
    },
    **{k: get_args(_TOPIC_HINTS[k]) for k in ("scope", "depth")},
}


def enum_choices(field_name: str) -> tuple[str, ...]:
    """The allowed words for an enum field — what the UI's dropdowns offer."""
    return _ENUMS[field_name]


def inputs_from_dict(data: Mapping[str, Any]) -> RunInputs:
    """Validate raw UI values into RunInputs, collecting every problem before raising.

    Blank list rows are dropped; a blank topic-spec title falls back to the topic and an
    empty objectives list to the CLI default (`Understand {topic}`), mirroring what
    `forged learn --topic` does when no spec is given.
    """
    problems: list[str] = []
    topic = _text(data.get("topic"), "topic", problems, required=True)
    raw_profile = _mapping(data.get("learner_profile"), "learner_profile", problems)
    raw_topic = _mapping(data.get("topic_spec"), "topic_spec", problems)

    profile = LearnerProfile(
        name=_text(raw_profile.get("name"), "learner_profile.name", problems, required=True),
        description=_text(raw_profile.get("description"), "learner_profile.description", problems),
        prior_knowledge=_rows(
            raw_profile.get("prior_knowledge"), "learner_profile.prior_knowledge", problems
        ),
        environment=_choice(raw_profile, "environment", "learner_profile", problems),
        material_density=_choice(raw_profile, "material_density", "learner_profile", problems),
        learning_style=_choice(raw_profile, "learning_style", "learner_profile", problems),
        background_context=_text(
            raw_profile.get("background_context"), "learner_profile.background_context", problems
        ),
    )
    objectives = _rows(
        raw_topic.get("learning_objectives"), "topic_spec.learning_objectives", problems
    )
    spec = TopicSpecification(
        title=_text(raw_topic.get("title"), "topic_spec.title", problems) or topic,
        scope=_choice(raw_topic, "scope", "topic_spec", problems),
        learning_objectives=objectives or [f"Understand {topic}"],
        prerequisites=_rows(raw_topic.get("prerequisites"), "topic_spec.prerequisites", problems),
        constraints=_text(raw_topic.get("constraints"), "topic_spec.constraints", problems),
        depth=_choice(raw_topic, "depth", "topic_spec", problems),
        focus_areas=_rows(raw_topic.get("focus_areas"), "topic_spec.focus_areas", problems),
    )
    if problems:
        raise InputError(problems)
    return RunInputs(topic=topic, learner_profile=profile, topic_spec=spec)


def _mapping(value: Any, name: str, problems: list[str]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    problems.append(f"{name}: must be an object")
    return {}


def _text(value: Any, name: str, problems: list[str], required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        problems.append(f"{name}: must be text")
        return ""
    text = value.strip()
    if required and not text:
        problems.append(f"{name}: must not be empty")
    return text


def _rows(value: Any, name: str, problems: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        problems.append(f"{name}: must be a list of rows, not {type(value).__name__}")
        return []
    if not all(isinstance(item, str) for item in value):
        problems.append(f"{name}: every row must be text")
        return []
    return [item.strip() for item in value if item.strip()]


def _choice(raw: Mapping[str, Any], key: str, prefix: str, problems: list[str]) -> Any:
    allowed = enum_choices(key)
    value = raw.get(key)
    if value not in allowed:
        problems.append(f"{prefix}.{key}: {value!r} is not one of {', '.join(allowed)}")
        return allowed[0]
    return value


# ── Preview / edit value objects ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModulePreview:
    number: int
    title: str
    lesson_mode: str | None
    scope: str
    depth: str
    objectives: tuple[str, ...]
    builds_on: tuple[str, ...]
    built: bool


@dataclass(frozen=True)
class PlanPreview:
    """Everything the plan gate shows, as data (and `text`: the CLI's own rendering)."""

    title: str
    rationale: str
    shape: str  # "lesson" (1 module) | "course" (N modules)
    modules: tuple[ModulePreview, ...]
    building: int
    estimate: str
    fidelity: str
    fidelity_status: str  # "covered" | "dropped" | "not_assessed"
    missing: tuple[str, ...]
    notes: tuple[str, ...]
    can_build: bool
    block_reason: str
    text: str


@dataclass(frozen=True)
class EditOutcome:
    plan: dict[str, Any]
    op: str = ""
    warning: str = ""
    confirmed: bool = False
    cancelled: bool = False
    replanned: bool = False


@dataclass(frozen=True)
class BuildOptions:
    max_modules: int | None = None
    provision: bool = True


@dataclass(frozen=True)
class Launch:
    run_dir: Path
    request_path: Path
    log_path: Path
    command: tuple[str, ...]
    pid: int | None  # None: a dry run, nothing was spawned


@dataclass(frozen=True)
class BuildRequest:
    """What the build subprocess reads. Holds no secret — the key travels via env."""

    stamp: str
    runs_root: Path
    inputs: RunInputs
    course: CourseSpec
    options: BuildOptions


# ── Launchers ───────────────────────────────────────────────────────────────────────


class Launcher(Protocol):
    def launch(
        self,
        command: Sequence[str],
        env_overrides: Mapping[str, str],
        log_path: Path,
        cwd: Path,
    ) -> int | None: ...

    def poll(self, pid: int) -> int | None: ...


class SubprocessLauncher:
    """Runs the build as an in-container child process (doc 25's default: single tenant,
    no queue). Output goes to the launch log; the key only into the child's env."""

    def __init__(self) -> None:
        self._procs: dict[int, subprocess.Popen[bytes]] = {}

    def launch(
        self,
        command: Sequence[str],
        env_overrides: Mapping[str, str],
        log_path: Path,
        cwd: Path,
    ) -> int:
        env = {**os.environ, **env_overrides}
        with open(log_path, "ab") as log:
            proc = subprocess.Popen(  # fixed argv, no shell
                list(command), cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
        self._procs[proc.pid] = proc
        return proc.pid

    def poll(self, pid: int) -> int | None:
        proc = self._procs.get(pid)
        return None if proc is None else proc.poll()

    def wait(self, pid: int, timeout: float) -> int:
        return self._procs[pid].wait(timeout=timeout)


class DryRunLauncher:
    """Records the command it would run and spawns nothing (the `--fake-llm` demo mode:
    a canned plan must never reach a real, paid build)."""

    def launch(
        self,
        command: Sequence[str],
        env_overrides: Mapping[str, str],
        log_path: Path,
        cwd: Path,
    ) -> None:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("dry run — nothing launched. Would run:\n  " + " ".join(command) + "\n")
        return None

    def poll(self, pid: int) -> int | None:
        return None


# ── The service ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ForgeService:
    personas_dir: Path = cli.DEFAULT_PERSONAS
    runs_root: Path = field(default_factory=lambda: Path.cwd() / "runs")
    llm_factory: LLMFactory | None = None
    launcher: Launcher = field(default_factory=SubprocessLauncher)

    def _client(self, model: str) -> Any:
        return None if self.llm_factory is None else self.llm_factory(model)

    def _planner(self) -> CurriculumPlanner:
        return CurriculumPlanner(
            personas_dir=self.personas_dir, llm_client=self._client(planner_mod.DEFAULT_MODEL)
        )

    def plan(self, inputs: RunInputs, api_key: str = "") -> dict[str, Any]:
        """Plan the topic exactly as `forged learn` does (planner + readiness pre-flight)."""
        planner = self._planner()
        assessor = ReadinessAssessor(
            personas_dir=self.personas_dir,
            llm_client=self._client(readiness_mod.DEFAULT_MODEL),
        )
        with _api_key_scope(api_key):
            course = planner.plan(
                brief=inputs.topic,
                learner_profile=inputs.learner_profile,
                topic_spec=inputs.topic_spec,
            )
            course = cli._apply_readiness_preflight(
                course, self.personas_dir, planner, inputs.topic,
                inputs.learner_profile, inputs.topic_spec, assessor=assessor,
            )
        return course_to_dict(course)

    def preview(
        self, plan: Mapping[str, Any], inputs: RunInputs, max_modules: int | None = None
    ) -> PlanPreview:
        course = course_from_dict(dict(plan))
        return _preview(course, inputs, max_modules)

    def edit(
        self,
        plan: Mapping[str, Any],
        op: str,
        targets: Sequence[int],
        mode: str | None = None,
    ) -> EditOutcome:
        """One deterministic gate op, straight to `apply_adjustment` — no classifier call.
        A malformed target raises ValueError, exactly as the CLI gate re-prompts on it."""
        if op not in EDIT_OPS:
            raise ValueError(f"unknown edit {op!r}; expected one of {', '.join(EDIT_OPS)}")
        instruction = ""
        if op == "set_mode":
            if mode not in LESSON_MODES:
                raise ValueError(f"choose a lesson mode: {', '.join(LESSON_MODES)}")
            instruction = mode
        course = course_from_dict(dict(plan))
        result = apply_adjustment(course, AdjustmentIntent(op, tuple(targets), instruction))
        return EditOutcome(
            plan=course_to_dict(result.course), op=op, warning=result.warning.strip()
        )

    def adjust(
        self, plan: Mapping[str, Any], sentence: str, inputs: RunInputs, api_key: str = ""
    ) -> EditOutcome:
        """The CLI gate's free-text round: classify, apply, or escalate to a re-plan."""
        sentence = (sentence or "").strip()
        if not sentence:
            raise InputError(["change: describe the change you want"])
        course = course_from_dict(dict(plan))
        adjuster = PlanAdjuster(
            personas_dir=self.personas_dir,
            llm_client=self._client(adjuster_mod.DEFAULT_MODEL),
        )
        titles = tuple(module.spec.title for module in course.modules)
        with _api_key_scope(api_key):
            intent = adjuster.classify(titles, sentence)
            result = apply_adjustment(course, intent)
            if result.needs_replan:
                replanned = self._planner().plan(
                    brief=inputs.topic,
                    learner_profile=inputs.learner_profile,
                    topic_spec=inputs.topic_spec,
                    guidance=intent.instruction,
                )
                return EditOutcome(plan=course_to_dict(replanned), op="replan", replanned=True)
        return EditOutcome(
            plan=course_to_dict(result.course),
            op=intent.op,
            warning=result.warning.strip(),
            confirmed=result.confirmed,
            cancelled=result.cancelled,
        )

    def build(
        self,
        plan: Mapping[str, Any],
        inputs: RunInputs,
        api_key: str = "",
        options: BuildOptions | None = None,
    ) -> Launch:
        """Launch the confirmed plan through the CLI's own build path, in a subprocess."""
        options = options or BuildOptions()
        key = _checked_key(api_key)
        course = course_from_dict(dict(plan))
        preview = _preview(course, inputs, options.max_modules)
        if not preview.can_build:
            raise ValueError(preview.block_reason)

        stamp = cli._run_stamp()
        run_dir = cli._planned_run_dir(course, inputs.topic, self.runs_root, stamp)
        run_dir.mkdir(parents=True, exist_ok=True)
        request = BuildRequest(stamp, Path(self.runs_root), inputs, course, options)
        request_path = run_dir / REQUEST_FILE
        request_path.write_text(json.dumps(_request_to_dict(request), indent=2), encoding="utf-8")
        log_path = run_dir / LAUNCH_LOG
        command = (sys.executable, "-m", "forged.service", "build", "--request", str(request_path))
        pid = self.launcher.launch(
            command, {API_KEY_ENV: key} if key else {}, log_path, Path.cwd()
        )
        return Launch(run_dir, request_path, log_path, command, pid)

    def status(self, launch: Launch) -> str:
        if launch.pid is None:
            return "dry run — nothing was launched (offline demo mode)"
        code = self.launcher.poll(launch.pid)
        if code is None:
            return f"running (pid {launch.pid})"
        verdict = "finished OK" if code == 0 else "see the launch log and SUMMARY.md"
        return f"exited with code {code} — {verdict}"


def _preview(course: CourseSpec, inputs: RunInputs, max_modules: int | None) -> PlanPreview:
    count = len(course.modules)
    building = count if max_modules is None else max(0, min(max_modules, count))
    requested = list(cli._requested_capabilities(inputs.topic_spec))
    missing: tuple[str, ...] = ()
    if not requested:
        status = "not_assessed"
    else:
        missing = assess_course_fidelity(requested, course).missing
        status = "dropped" if missing else "covered"

    shape = "lesson" if count == 1 else "course"
    notes: list[str] = []
    if shape == "lesson":
        notes.append(
            "A single lesson: no course-level fidelity gate — topic fidelity is checked "
            "per lesson during the run (R1)."
        )
    homogeneous = _render_homogeneous_mode_warning(course).strip()
    if homogeneous:
        notes.append(homogeneous.lstrip("⚠ "))
    block_reason = ""
    if shape == "course" and status == "dropped":
        block_reason = "the decomposition dropped: " + "; ".join(missing)
    elif building == 0:
        block_reason = "no modules would be built"
    return PlanPreview(
        title=course.title,
        rationale=course.rationale,
        shape=shape,
        modules=tuple(
            ModulePreview(
                number=m.order,
                title=m.spec.title,
                lesson_mode=m.lesson_mode,
                scope=m.spec.scope,
                depth=m.spec.depth,
                objectives=tuple(m.spec.learning_objectives),
                builds_on=m.module_prerequisites,
                built=m.order < building,
            )
            for m in course.modules
        ),
        building=building,
        estimate=_render_estimate(building, capped=building < count).strip(),
        fidelity=_render_fidelity(course, requested).strip(),
        fidelity_status=status,
        missing=tuple(missing),
        notes=tuple(notes),
        can_build=not block_reason,
        block_reason=block_reason,
        text=render_plan(course, requested, max_modules),
    )


# ── BYOK ────────────────────────────────────────────────────────────────────────────


def _checked_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if any(ch.isspace() or not ch.isprintable() for ch in key):
        raise InputError(["API key: must not contain spaces or control characters"])
    return key


@contextmanager
def _api_key_scope(api_key: str) -> Iterator[None]:
    """Expose the key to in-process LLM clients for one call, then restore the env."""
    key = _checked_key(api_key)
    if not key:
        yield
        return
    with _KEY_LOCK:
        previous = os.environ.get(API_KEY_ENV)
        os.environ[API_KEY_ENV] = key
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(API_KEY_ENV, None)
            else:
                os.environ[API_KEY_ENV] = previous


def key_in_environment() -> bool:
    """Whether the process already has a key (e.g. `docker run -e OPENAI_API_KEY`)."""
    return bool(os.environ.get(API_KEY_ENV))


# ── The build request (subprocess hand-off) ─────────────────────────────────────────


def _request_to_dict(request: BuildRequest) -> dict[str, Any]:
    return {
        "version": REQUEST_VERSION,
        "stamp": request.stamp,
        "runs_root": str(request.runs_root),
        "inputs": inputs_to_dict(request.inputs),
        "course": course_to_dict(request.course),
        "options": asdict(request.options),
    }


def load_request(path: Path) -> BuildRequest:
    """Read and validate a build request; raises ValueError naming the problem."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: build request must be a JSON object")
    version = data.get("version")
    if version != REQUEST_VERSION:
        raise ValueError(
            f"{path}: request version {version!r} is not supported "
            f"(this forged reads version {REQUEST_VERSION})"
        )
    raw_options = data.get("options") or {}
    max_modules = raw_options.get("max_modules")
    if max_modules is not None and (not isinstance(max_modules, int) or max_modules < 1):
        raise ValueError(f"{path}: options.max_modules must be a positive integer or null")
    return BuildRequest(
        stamp=str(data["stamp"]),
        runs_root=Path(data["runs_root"]),
        inputs=inputs_from_dict(data["inputs"]),
        course=course_from_dict(data["course"]),
        options=BuildOptions(
            max_modules=max_modules, provision=bool(raw_options.get("provision", True))
        ),
    )


def _cmd_build(request_path: Path, err: IO[str]) -> int:
    try:
        request = load_request(request_path)
        pipeline = cli.load_pipeline(str(cli.DEFAULT_CONFIG))
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(f"✗ cannot read build request: {exc}", file=err)
        return cli.EXIT_USAGE

    cli._load_dotenv(Path.cwd() / ".env")
    cli._load_dotenv(cli.PACKAGE_ROOT / ".env")
    args = argparse.Namespace(
        runs=str(request.runs_root),
        no_provision=not request.options.provision,
        max_modules=request.options.max_modules,
        debug=False,
        redecompose=False,
        max_depth=1,
    )
    inputs = request.inputs
    return cli._build_confirmed(
        args, request.course, inputs.learner_profile, inputs.topic, pipeline,
        cli.DEFAULT_PERSONAS, list(cli._requested_capabilities(inputs.topic_spec)),
        stamp=request.stamp,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m forged.service",
        description="Build a plan confirmed in the UI (launched by `forged ui`).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Build the confirmed plan in a UI build request")
    build.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    return _cmd_build(args.request, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
