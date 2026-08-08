"""forged — build an executed, critiqued teaching notebook from a topic.

There is one front door. `forged learn` plans first and decides for itself whether the
topic is one lesson or a course of modules; you confirm the plan before anything paid
runs. There is deliberately no separate "single lesson" vs "course" command — picking
between them was a judgement the learner had no basis to make, and getting it wrong is
what produced over-large lessons.

  1. MINIMAL INPUT (uses sensible defaults):
    forged learn --topic "How a hash map works"

  2. STRUCTURED INPUT (customize learner profile and topic):
    forged learn --topic "Hash maps" \
      --learner-profile templates/examples/learner-backend-junior.yaml \
      --topic-spec templates/examples/topic-hash-maps.yaml

  3. SEE THE PLAN WITHOUT SPENDING ON MODULES:
    forged learn --topic "Hash maps" --plan-only

Other commands:
  forged pipelines            # list the bundled pipeline configs
  forged clean --keep 10      # prune old runs (asks before deleting)

Template files:
  Copy templates from templates/examples/ or create your own following
  templates/learner_profile.template.yaml. See templates/README.md for details.

Bundled defaults (pipeline configs, personas) ship with the package. Run output
is written to ./runs in the current working directory. Keys are read from the
environment or a local .env (OPENAI_API_KEY, or OLLAMA_BASE_URL for local inference).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import load_pipeline
from .context import build_context_block, topic_spec_to_json
from .curriculum.assembler import assemble_course
from .curriculum.fidelity import assess_course_fidelity, assessable_capabilities
from .curriculum.model import topic_capabilities
from .curriculum.planner import CurriculumPlanner
from .curriculum.readiness import ReadinessAssessor
from .deliverables import (
    write_agentic_summary,
    write_final_notebook,
    write_learner_package,
)
from .models import LearnerProfile, TopicSpecification
from .pipeline.mode import render_mode_directive
from .progress import Spinner
from .usage import write_usage_report

# Repository/package root — where the bundled config/personas live.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "pipeline.review-loop.yaml"
DEFAULT_PERSONAS = PACKAGE_ROOT / "personas"

# Exit codes: 0 ok, 1 runtime failure, 2 bad input / usage.
EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "clean":
        return _cmd_clean(args)
    if args.command == "pipelines":
        return _cmd_pipelines(args)
    return _cmd_learn(args)


def _cmd_clean(args) -> int:
    """Prune old run directories, keeping the newest --keep. Manual only — never runs
    automatically, and never deletes without confirmation (or an explicit --yes)."""
    if args.keep < 0:
        print("✗ --keep must be >= 0", file=sys.stderr)
        return EXIT_USAGE

    runs_root = Path(args.runs)
    if not runs_root.is_dir():
        print(f"No runs directory at {runs_root} — nothing to clean.")
        return EXIT_OK

    run_dirs = sorted((p for p in runs_root.iterdir() if p.is_dir()), reverse=True)
    to_remove = run_dirs[args.keep:]
    if not to_remove:
        print(f"{len(run_dirs)} run(s) present; keeping newest {args.keep} — nothing to remove.")
        return EXIT_OK

    if args.dry_run:
        print(f"Would remove {len(to_remove)} run(s) (keeping newest {args.keep}):")
        for path in to_remove:
            print(f"  {path.name}")
        print("Dry run — nothing deleted.")
        return EXIT_OK

    if not args.yes and not _confirm_delete(len(to_remove), args.keep):
        return EXIT_OK if sys.stdin.isatty() else EXIT_RUNTIME

    for path in to_remove:
        shutil.rmtree(path)
    print(f"Removed {len(to_remove)} old run(s); kept newest {args.keep}.")
    return EXIT_OK


def _confirm_delete(count: int, keep: int) -> bool:
    """Ask before an irreversible delete. Non-interactive callers must pass --yes —
    we refuse rather than guess, so a script can't wipe runs by accident."""
    if not sys.stdin.isatty():
        print(
            f"✗ Refusing to delete {count} run(s) without confirmation. "
            "Pass --yes to proceed, or --dry-run to preview.",
            file=sys.stderr,
        )
        return False
    answer = input(f"Delete {count} run(s), keeping newest {keep}? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted — nothing deleted.")
        return False
    return True


def _run_agentic_lesson(
    topic: str,
    learner_profile,
    topic_spec,
    pipeline,
    personas_dir: Path,
    run_dir: Path,
    provision: bool,
    debug: bool,
    lesson_mode=None,
) -> int:
    """Run one lesson through the agentic pipeline and write its deliverables.

    The shared single-lesson entry point behind both `forged agentic` and the smart
    front door's 1-module branch (doc 16): given a resolved topic spec + learner profile,
    it provisions, runs the pipeline, writes lesson.ipynb / SUMMARY.md / the learner
    package / usage, and returns an honest exit code (0 only on an acceptable notebook).

    `lesson_mode`, when set, is a mode already decided upstream (the operator at the plan
    gate) and is handed down as binding — this branch bypasses the course orchestrator, so
    without it a 1-module plan would silently drop the override (doc 18, D3).
    """
    import asyncio
    import logging
    from datetime import datetime

    from .artifacts import ArtifactStore
    from .logging_config import setup_logging
    from .pipeline.graph import run_pipeline
    from .pipeline.state import create_initial_state

    run_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(debug=debug, log_file=run_dir / "pipeline.log")
    logger = logging.getLogger(__name__)

    if not personas_dir.is_dir():
        print(f"✗ personas directory not found: {personas_dir}", file=sys.stderr)
        return EXIT_RUNTIME

    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(PACKAGE_ROOT / ".env")

    logger.info("Agentic pipeline starting (run_dir=%s)", run_dir)
    start_time = datetime.now()

    try:
        store = ArtifactStore(run_dir)
        from .artifacts import Artifact

        store.put(Artifact(name="brief", kind="text", content=topic))
        # The shared learner + topic context block; every LLM agent reads this
        # (see forged.context, forged.pipeline.agents.Agent._context_prefix).
        context_block = build_context_block(learner_profile, topic_spec)
        directive = render_mode_directive(lesson_mode)
        if directive:
            context_block = (
                f"{context_block}{directive}" if context_block else directive.lstrip()
            )
        if context_block:
            store.put(Artifact(name="lesson_context", kind="text", content=context_block))
        # Structured counterpart to lesson_context: the requested capabilities as
        # data, so the deterministic topic-fidelity detector can check coverage
        # without re-parsing prose (see docs/architecture/11-topic-fidelity-r1.md).
        store.put(
            Artifact(name="topic_spec", kind="json", content=topic_spec_to_json(topic_spec))
        )

        state = create_initial_state(run_id=run_dir.name)
        logger.info("Initial state created (run_id=%s, iteration=0)", state.run_id)

        final_state = asyncio.run(
            run_pipeline(state, store, pipeline, personas_dir, provision=provision)
        )

        elapsed_sec = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Pipeline complete (terminal=%s, elapsed=%.1fs)",
            final_state.is_terminal,
            elapsed_sec,
        )

        write_agentic_summary(run_dir, final_state, elapsed_sec)
        write_final_notebook(run_dir, store, final_state)
        write_learner_package(run_dir, store, final_state, topic, learner_profile)
        # Per-call token usage (input/output/cached split) captured during the run.
        write_usage_report(run_dir, final_state.run_id)

        # Exit-code truth: 0 only when the pipeline ended because the notebook
        # was ACCEPTABLE. Errors, budget exhaustion, and unclassifiable runs
        # are terminal too — but they are not success and must not exit 0.
        if final_state.is_terminal and final_state.terminal_ok:
            print(f"\n✓ Agentic pipeline complete — open {run_dir / 'lesson.ipynb'}")
            print(f"  summary  {run_dir / 'SUMMARY.md'}")
            if final_state.degradations:
                # Acceptable, but not pristine: never let a fallback pass unmentioned.
                print(
                    f"  ⚠ {len(final_state.degradations)} degradation(s) occurred during "
                    f"the run — see the Degradations section in SUMMARY.md",
                    file=sys.stderr,
                )
            return EXIT_OK
        if final_state.is_terminal:
            print(
                f"\n✗ Pipeline ended without an acceptable notebook: "
                f"{final_state.terminal_reason}",
                file=sys.stderr,
            )
            print(f"  review {run_dir / 'SUMMARY.md'} before using the output", file=sys.stderr)
            return EXIT_RUNTIME
        print(f"\n⚠ Pipeline did not terminate — check {run_dir / 'SUMMARY.md'}", file=sys.stderr)
        return EXIT_RUNTIME

    except Exception as exc:
        logger.exception("Agentic pipeline failed: %s", exc)
        print(f"\n✗ Pipeline failed: {exc}", file=sys.stderr)
        return EXIT_RUNTIME


def _cmd_pipelines(args) -> int:
    """List the bundled pipeline configs so users can discover them without ls'ing
    the package directory."""
    config_dir = PACKAGE_ROOT / "config"
    configs = sorted(config_dir.glob("pipeline.*.yaml"))
    if not configs:
        print(f"No bundled pipelines found in {config_dir}.")
        return EXIT_OK
    print("Available pipelines (pass the path with --config):\n")
    for path in configs:
        name = path.stem.replace("pipeline.", "")
        print(f"  {name:<14} {path}")
    return EXIT_OK


def _finalize_course(result, course_dir: Path, fidelity) -> int:
    """Assemble the course deliverable (README/COURSE.md/NAV.md, doc 13 Phase 3) from
    the course's outcome, then print the per-module status report. Shared by
    `_cmd_course` and `_build_confirmed` so both entry points assemble identically."""
    assemble_course(result, course_dir, fidelity=fidelity)
    return _report_course_result(result, course_dir)


def _orchestrate_course(course, learner_profile, course_dir, *, pipeline, personas_dir, args):
    """Run a course sequentially, or (opt-in via `--redecompose`) with the reactive safety
    net that re-decomposes any module still dropping a capability (doc 13, Phase 4)."""
    from .curriculum.orchestrator import run_course

    provision = not getattr(args, "no_provision", False)
    if getattr(args, "redecompose", False):
        from .curriculum.reactive import run_course_reactive

        return run_course_reactive(
            course, learner_profile, course_dir,
            pipeline=pipeline, personas_dir=personas_dir,
            plan_remediation=_make_remediation_planner(personas_dir),
            provision=provision,
            max_modules=args.max_modules,
            max_depth=getattr(args, "max_depth", 1),
        )
    return run_course(
        course, learner_profile, course_dir,
        pipeline=pipeline, personas_dir=personas_dir,
        provision=provision, max_modules=args.max_modules,
    )


def _make_remediation_planner(personas_dir: Path):
    """Build the reactive loop's remediation planner: dropped capabilities → new module
    spec(s), via the same CurriculumPlanner, one altitude down (follow-on modules only)."""
    from .curriculum.planner import CurriculumPlanner

    planner = CurriculumPlanner(personas_dir=personas_dir)

    def _plan(dropped, profile):
        brief = (
            "An earlier lesson could not fit these capabilities. Plan focused follow-on "
            "module(s) that cover them, assuming everything else is already known:\n"
            + "\n".join(f"- {c}" for c in dropped)
        )
        try:
            spec = planner.plan(brief=brief, learner_profile=profile, topic_spec=None)
        except Exception as exc:  # noqa: BLE001 - a failed re-plan must not abort the course
            print(f"  ⚠ remediation planning failed: {exc}", file=sys.stderr)
            return ()
        return tuple(m.spec for m in spec.modules)

    return _plan


def _dir_slug(text: str) -> str:
    """Filesystem-safe short slug for a course directory name."""
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:30] or "course"


def _report_course_result(result, course_dir: Path) -> int:
    """Print per-module status; EXIT_OK only when every module reached an acceptable
    notebook. Failures are reported, never hidden."""
    ok = sum(1 for m in result.modules if m.terminal_ok)
    total = len(result.modules)
    print(f"\nCourse complete: {ok}/{total} module(s) acceptable — {course_dir}")
    for m in result.modules:
        mark = "✓" if m.terminal_ok else "✗"
        nb = m.notebook_path or "(no notebook)"
        print(f"  {mark} [{m.module.order}] {m.module.spec.title} → {nb}")
        dropped = [cap for sig in m.topic_fidelity for cap in sig.missing]
        if dropped:
            print(f"      ⚠ still dropped: {'; '.join(dropped)}", file=sys.stderr)
    if ok < total:
        print(
            f"  ⚠ {total - ok} module(s) did not reach an acceptable notebook — "
            f"see each module's SUMMARY.md",
            file=sys.stderr,
        )
        return EXIT_RUNTIME
    return EXIT_OK


def _cmd_learn(args) -> int:
    """The front door (doc 16): plan first, confirm, then build a lesson or a course.

    Always calls the CurriculumPlanner (the sizing authority): 1 module → the single-lesson
    branch; N modules → course orchestration. Both branches are reached from here and only
    from here — the old `agentic`/`course`/`build` commands made the caller pre-commit to a
    shape before anything had sized the topic. The interactive gate runs nothing paid until
    the learner confirms; `--yes` skips it, and a non-TTY stdin without `--yes` is a usage
    error so a script must opt into spending explicitly. `--plan-only` stops after the plan.
    """
    topic = (args.topic or "").strip()
    if not topic:
        print("✗ --topic must not be empty", file=sys.stderr)
        return EXIT_USAGE

    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(PACKAGE_ROOT / ".env")

    try:
        pipeline = load_pipeline(args.config)
        learner_profile = (
            LearnerProfile.from_yaml(args.learner_profile)
            if args.learner_profile
            else _default_learner_profile()
        )
        topic_spec = (
            TopicSpecification.from_yaml(args.topic_spec)
            if args.topic_spec
            else _default_topic_spec(topic)
        )
    except (FileNotFoundError, ValueError, TypeError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return EXIT_USAGE

    personas_dir = Path(args.personas)
    try:
        planner = CurriculumPlanner(personas_dir=personas_dir)
        course = planner.plan(
            brief=topic, learner_profile=learner_profile, topic_spec=topic_spec
        )
    except Exception as exc:
        print(f"\n✗ Curriculum planning failed: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    course = _apply_readiness_preflight(
        course, personas_dir, planner, topic, learner_profile, topic_spec
    )

    original_capabilities = list(_requested_capabilities(topic_spec))

    # --plan-only: show the plan and the union-coverage verdict, then stop. Costs the
    # planner (and the readiness pre-flight) only — no module is ever built.
    if args.plan_only:
        return _report_plan_only(course, original_capabilities, args.out)

    # The gate: plan first, confirm before spending. --yes accepts as-is (still printed);
    # a non-TTY stdin without --yes is a usage error so a script opts into spending.
    if args.yes:
        _print_course(course)
        print("\n▶ --yes given: building without the interactive gate.")
        confirmed_course = course
    elif not sys.stdin.isatty():
        print(
            "✗ the interactive plan gate needs a TTY; pass --yes to run non-interactively",
            file=sys.stderr,
        )
        return EXIT_USAGE
    else:
        confirmed_course = _run_plan_gate(
            course, original_capabilities, personas_dir, planner,
            topic, learner_profile, topic_spec,
        )
        if confirmed_course is None:
            print("\nNothing was run.")
            return EXIT_OK  # a deliberate 'no' / cancelled gate is a success, not an error

    return _build_confirmed(
        args, confirmed_course, learner_profile, topic, pipeline, personas_dir,
        original_capabilities,
    )


def _report_plan_only(course, requested_capabilities: list[str], out: Path | None) -> int:
    """Print the plan plus its union-coverage verdict; persist it when --out is given.

    A decomposition that dropped a requested capability is an honest failure (non-zero
    exit), never a silent success — the same invariant the build path enforces before it
    spends, surfaced here for free.
    """
    report = assess_course_fidelity(requested_capabilities, course)
    _print_course(course)

    if not report.is_faithful:
        print(
            "\n  ⚠ course-fidelity check FAILED — the decomposition dropped: "
            + "; ".join(report.missing),
            file=sys.stderr,
        )
        return EXIT_RUNTIME

    if out:
        _persist_course(Path(out), course, report)
    print("\n  ✓ course-fidelity check passed — every requested capability is covered")
    return EXIT_OK


def _apply_readiness_preflight(
    course, personas_dir: Path, planner, topic: str, learner_profile, topic_spec
):
    """Doc 14 Part III: before any paid build, check whether a plan the CurriculumPlanner
    sized to a single module is honestly reachable for this learner.

    Only runs for a 1-module plan — an N-module course already went through the planner's
    own decomposition judgment. On an unreachable verdict, escalates via a guided re-plan
    (the same Tier-2 guidance channel the front-door gate's PlanAdjuster uses), producing
    an N-module course that flows into the existing, unchanged gate/build path. Fails open
    (returns the original plan) on any re-plan error — never blocks a build over an
    escalation attempt that itself failed.
    """
    if len(course.modules) != 1:
        return course

    assessor = ReadinessAssessor(personas_dir=personas_dir)
    verdict = assessor.assess(
        brief=topic, learner_profile=learner_profile, topic_spec=topic_spec
    )
    if verdict.reachable:
        return course

    print(
        f"\n⚠ Readiness check: {verdict.reason} — replanning as a course.",
        file=sys.stderr,
    )
    try:
        return planner.plan(
            brief=topic, learner_profile=learner_profile, topic_spec=topic_spec,
            guidance=_readiness_escalation_guidance(verdict),
        )
    except Exception as exc:  # noqa: BLE001 - fail open: keep the original single-lesson plan
        print(
            f"  ⚠ readiness escalation re-plan failed, proceeding as-is: {exc}",
            file=sys.stderr,
        )
        return course


def _readiness_escalation_guidance(verdict) -> str:
    """Synthesize the guidance sentence for the planner's Tier-2 re-plan channel from a
    not-reachable ReadinessVerdict."""
    foundations = "; ".join(verdict.missing_foundations) or "the missing prerequisites"
    return (
        f"{verdict.reason} Split this into an ordered course that first teaches "
        f"{foundations}, then proceeds to the original topic."
    )


def _run_plan_gate(
    course, original_capabilities, personas_dir, planner,
    topic, learner_profile, topic_spec,
):
    """Run the interactive gate; return the confirmed course, or None if it cancelled."""
    from .curriculum.adjuster import PlanAdjuster
    from .curriculum.gate import run_gate

    adjuster = PlanAdjuster(personas_dir=personas_dir)

    def _replanner(_current, sentence):
        return planner.plan(
            brief=topic,
            learner_profile=learner_profile,
            topic_spec=topic_spec,
            guidance=sentence,
        )

    outcome = run_gate(
        course,
        original_capabilities,
        adjuster,
        _replanner,
        input_stream=sys.stdin,
        output_stream=sys.stdout,
    )
    return outcome.course if outcome.confirmed else None


def _build_confirmed(
    args, course, learner_profile, topic, pipeline, personas_dir, original_capabilities
) -> int:
    """Build a confirmed plan: 1 module → single lesson, N modules → course orchestration."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    provision = not getattr(args, "no_provision", False)

    if len(course.modules) == 1:
        module = course.modules[0]
        run_dir = Path(args.runs) / f"{stamp}_{_dir_slug(module.spec.title)}"
        print(f"\n▶ Running 1 module lesson into {run_dir} …")
        return _run_agentic_lesson(
            topic=module.spec.title,
            learner_profile=learner_profile,
            topic_spec=module.spec,
            pipeline=pipeline,
            personas_dir=personas_dir,
            run_dir=run_dir,
            provision=provision,
            debug=args.debug,
            lesson_mode=module.lesson_mode,
        )

    report = assess_course_fidelity(list(original_capabilities), course)

    # A decomposition that dropped a requested capability is never run — fail honestly
    # first. This gate lived in the old `forged course` command; without it here, folding
    # that command into `learn` would have quietly deleted the union-coverage guarantee
    # the README promises. `original_capabilities` is already the *assessable* subset
    # (`_requested_capabilities`), so a free-text paragraph topic yields an empty list and
    # a vacuously faithful report — this blocks a real drop, never an unmeasurable one,
    # and so agrees with the "ⓘ not assessed" verdict the plan gate prints.
    if not report.is_faithful:
        print(
            "\n  ⚠ course-fidelity check FAILED — the decomposition dropped: "
            + "; ".join(report.missing),
            file=sys.stderr,
        )
        return EXIT_RUNTIME

    course_dir = Path(args.runs) / f"{stamp}_course_{_dir_slug(topic)}"
    course_dir.mkdir(parents=True, exist_ok=True)
    _persist_course(course_dir, course, report)

    total = len(course.modules)
    n = total if args.max_modules is None else min(args.max_modules, total)
    print(f"\n▶ Running {n} module lesson(s) into {course_dir} …")
    result = _orchestrate_course(
        course, learner_profile, course_dir,
        pipeline=pipeline, personas_dir=personas_dir, args=args,
    )
    return _finalize_course(result, course_dir, report)


def _persist_course(out_dir: Path, course, report) -> None:
    """Write the course plan to <out>/course_plan.json + <out>/COURSE.md."""
    import json

    from .curriculum.model import course_to_dict

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "course": course_to_dict(course),
        "fidelity": {
            "is_faithful": report.is_faithful,
            "covered": list(report.covered),
            "missing": list(report.missing),
        },
    }
    (out_dir / "course_plan.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (out_dir / "COURSE.md").write_text(_render_course_md(course, report), encoding="utf-8")
    print(f"\n  ↳ plan written to {out_dir / 'course_plan.json'} and {out_dir / 'COURSE.md'}")


def _render_course_md(course, report) -> str:
    """A human-readable course index for the plan-only dry run."""
    lines = [f"# {course.title}", "", f"_{len(course.modules)} module(s)_", ""]
    if course.rationale:
        lines += [f"**Rationale:** {course.rationale}", ""]
    for module in course.modules:
        lines.append(f"## [{module.order}] {module.spec.title} ({module.spec.depth})")
        for objective in module.spec.learning_objectives:
            lines.append(f"- {objective}")
        if module.module_prerequisites:
            lines.append(f"\n_Builds on: {', '.join(module.module_prerequisites)}_")
        lines.append("")
    verdict = "✓ covers every requested capability" if report.is_faithful else (
        "⚠ DROPPED: " + "; ".join(report.missing)
    )
    lines += ["---", "", f"**Course-fidelity:** {verdict}", ""]
    return "\n".join(lines)


def _print_course(course) -> None:
    """Render a CourseSpec to stdout for the plan-only dry run."""
    print(f"\nCourse: {course.title}")
    print(f"  {len(course.modules)} module(s)")
    if course.rationale:
        print(f"  Rationale: {course.rationale}")
    for module in course.modules:
        print(f"\n  [{module.order}] {module.spec.title}  ({module.spec.depth})")
        for objective in module.spec.learning_objectives:
            print(f"      - {objective}")
        if module.module_prerequisites:
            print(f"      builds on: {', '.join(module.module_prerequisites)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forged",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pipelines", help="List the bundled pipeline configs")

    learn = sub.add_parser(
        "learn",
        help="Plan first, confirm, then build a lesson or a course (the front door)",
    )
    learn.add_argument("--topic", required=True, help="What you want to learn")
    learn.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive plan gate and build the proposed plan as-is "
             "(required for non-interactive/scripted use).",
    )
    learn.add_argument(
        "--plan-only", action="store_true",
        help="Produce and check the plan without building any lesson (no module run "
             "cost). Omit to continue to the confirmation gate and build.",
    )
    learn.add_argument(
        "--out",
        type=Path,
        help="With --plan-only, persist the plan into this directory "
             "(course_plan.json + COURSE.md). Ignored otherwise.",
    )
    learn.add_argument(
        "--config", default=str(DEFAULT_CONFIG),
        help="Pipeline YAML used to resolve stage-specific models (default: bundled "
             "review-loop).",
    )
    learn.add_argument(
        "--runs", default=str(Path.cwd() / "runs"),
        help="Root directory for run output (default: ./runs).",
    )
    learn.add_argument(
        "--max-modules", type=int, default=None,
        help="Cap the number of module lessons actually run when the plan is a course "
             "(cost control).",
    )
    learn.add_argument(
        "--redecompose", action="store_true",
        help="Enable the reactive safety net for a course plan: a module that still drops "
             "a capability is re-decomposed into a new module and run (opt-in; adds cost).",
    )
    learn.add_argument(
        "--max-depth", type=int, default=1,
        help="Max reactive re-decomposition rounds when --redecompose is set (default: 1).",
    )
    learn.add_argument(
        "--no-provision", action="store_true",
        help="Skip per-lesson virtualenv provisioning; run on the base kernel.",
    )
    learn.add_argument(
        "--learner-profile",
        type=Path,
        help="Path to learner_profile.yaml. Uses a sensible default if omitted.",
    )
    learn.add_argument(
        "--topic-spec",
        type=Path,
        help="Path to topic_specification.yaml. Uses a sensible default if omitted.",
    )
    learn.add_argument(
        "--debug", action="store_true",
        help="Enable DEBUG logging for a single-lesson build.",
    )
    learn.add_argument("--personas", default=str(DEFAULT_PERSONAS), help=argparse.SUPPRESS)

    clean = sub.add_parser("clean", help="Prune old run directories (manual, confirmed)")
    clean.add_argument(
        "--keep", type=int, default=10,
        help="Number of most-recent runs to keep (default: 10)",
    )
    clean.add_argument(
        "--yes", action="store_true",
        help="Skip the confirmation prompt (required for non-interactive use)",
    )
    clean.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be removed without deleting anything",
    )
    clean.add_argument(
        "--runs", default=str(Path.cwd() / "runs"),
        help="Root directory for run outputs (default: ./runs)",
    )
    return parser


def _default_learner_profile() -> LearnerProfile:
    """Sensible defaults when no profile is provided."""
    return LearnerProfile(
        name="Default Learner",
        description="Self-study for professional development",
        prior_knowledge=["Basic understanding of the topic"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="Self-directed learning; prefers practical examples",
    )


def _default_topic_spec(topic: str) -> TopicSpecification:
    """Sensible defaults when no topic spec is provided.

    `focus_areas` no longer repeats the topic. It used to, so a bare `--topic` produced
    two near-duplicate pseudo-capabilities (`f"Understand {topic}"` and `topic`); because
    distinctive terms are computed *among* the requested set, the pair cancelled each
    other down to the single word "understand", which no module title ever contains. One
    capability, not two restatements of one.

    Whether that capability is *assessable* is a separate question, decided by
    `forged.curriculum.fidelity.assessable_capabilities` — a one-line topic has a
    distinctive-term signature, a 60-word paragraph does not.
    """
    return TopicSpecification(
        title=topic,
        scope="implementation",
        learning_objectives=[f"Understand {topic}"],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[],
    )


class _StageReporter:
    """Streams a live per-stage status line, with a spinner during the long, silent
    LLM calls so the terminal never looks hung. Stateful: it owns the active spinner
    between the `start` and `done`/`error` callbacks for a single stage."""

    def __init__(self) -> None:
        self._spinner: Spinner | None = None

    def __call__(self, name: str, status: str, detail: str) -> None:
        if status == "start":
            self._spinner = Spinner(f"{name}  ({detail})").start()
            return
        self.abort()
        glyph = {"done": "✓", "error": "✗"}.get(status, "·")
        print(f"  {glyph} {name}  → {detail}")

    def abort(self) -> None:
        """Stop and clear any in-flight spinner (on stage completion or failure)."""
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, no external dependency. Does not
    overwrite variables already present in the environment."""
    import os

    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _requested_capabilities(topic_spec) -> tuple[str, ...]:
    """The capabilities the course-fidelity check can honestly measure.

    `topic_capabilities` returns everything the spec asked for; this drops the entries
    term-coverage cannot judge (a free-text brief is a paragraph, not a capability — see
    `forged.curriculum.fidelity.assessable_capabilities`). Empty means the check is
    reported as *not assessed*, never as passed or dropped.
    """
    return assessable_capabilities(topic_capabilities(topic_spec))


# Nothing may be defined below this guard: `python -m forged.cli` executes main() here,
# so a def placed after it does not exist yet when the command runs (import-based tests
# still pass, which is exactly why this needs a comment and a test).
if __name__ == "__main__":
    raise SystemExit(main())
