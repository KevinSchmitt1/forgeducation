"""forged — build an executed, critiqued teaching notebook from a topic.

Modes of Operation:

  1. MINIMAL INPUT (uses sensible defaults):
    forged build --topic "How a hash map works"

  2. STRUCTURED INPUT (customize learner profile and topic):
    forged build --topic "Hash maps" \
      --learner-profile templates/examples/learner-backend-junior.yaml \
      --topic-spec templates/examples/topic-hash-maps.yaml

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
import json
import shutil
import sys
from pathlib import Path

from .config import load_pipeline
from .context import build_context_block, topic_spec_to_json
from .models import LearnerProfile, TopicSpecification
from .orchestrator import MANIFEST_FILE, Orchestrator
from .progress import Spinner

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
    if args.command == "agentic":
        return _cmd_agentic(args)
    return _cmd_build(args)


def _cmd_build(args) -> int:
    topic = (args.topic or "").strip()
    if not topic:
        print("✗ --topic must not be empty", file=sys.stderr)
        return EXIT_USAGE

    # Keys come from the environment or a local .env (current dir or package root).
    _load_dotenv(Path.cwd() / ".env")
    _load_dotenv(PACKAGE_ROOT / ".env")

    try:
        pipeline = load_pipeline(args.config)

        # Load structured inputs (or use defaults)
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

    orchestrator = Orchestrator(
        pipeline=pipeline,
        personas_dir=Path(args.personas),
        runs_root=Path(args.runs),
    )

    profile_label = (
        Path(args.learner_profile).name
        if args.learner_profile
        else "default"
    )
    print(_build_header(pipeline, profile_label))
    reporter = _StageReporter()
    try:
        store = orchestrator.run(
            brief=topic,
            learner_profile=learner_profile,
            topic_spec=topic_spec,
            on_stage=reporter,
        )
    except Exception as exc:  # noqa: BLE001 — top-level: report cleanly, exit non-zero
        reporter.abort()
        # Flush the (block-buffered when piped) stdout header + stage lines before the
        # unbuffered stderr error, so the failure message can't jump ahead of them.
        sys.stdout.flush()
        print(f"\n✗ pipeline failed: {exc}", file=sys.stderr)
        if orchestrator.last_run_dir is not None:
            print(f"  debug files: {orchestrator.last_run_dir}", file=sys.stderr)
        return EXIT_RUNTIME

    return _report_outcome(store)


def _report_outcome(store) -> int:
    """Translate the gate's verdict into the user-facing message + exit code, so the
    CLI never reports success on a notebook the gate considers unusable."""
    gate = json.loads(store.read_file(MANIFEST_FILE)).get("gate", {})
    notebook = store.run_dir / "lesson.ipynb"
    summary = store.run_dir / "SUMMARY.md"

    if gate.get("crucial_open"):
        print("\n⚠ shipped with crucial issue(s) still open — review before use.")
        print(f"  open    {notebook}")
        print(f"  summary {summary}")
        return EXIT_RUNTIME
    if not gate.get("satisfied", True):
        print("\n⚠ done — below the quality bar; minor issues left for human review.")
        print(f"  open    {notebook}")
        print(f"  summary {summary}")
        return EXIT_OK

    print(f"\n✓ done — open {notebook}")
    print(f"  summary {summary}")
    return EXIT_OK


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


def _cmd_agentic(args) -> int:
    """Run the agentic pipeline with agent iteration and rerouting.

    Invokes run_pipeline() with structured feedback loop so agents can
    iterate on failures (Phase 8-9).
    """
    import asyncio
    import logging
    from datetime import datetime

    from .artifacts import ArtifactStore
    from .logging_config import setup_logging
    from .pipeline.graph import run_pipeline
    from .pipeline.state import create_initial_state

    topic = (args.topic or "").strip()
    if not topic:
        print("✗ --topic must not be empty", file=sys.stderr)
        return EXIT_USAGE

    # Same structured-input contract as `forged build`: load the learner profile
    # and topic spec (or sensible defaults), failing fast on bad input.
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

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(debug=args.debug, log_file=run_dir / "pipeline.log")
    logger = logging.getLogger(__name__)

    personas_dir = Path(args.personas)
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

        provision = not getattr(args, "no_provision", False)
        final_state = asyncio.run(
            run_pipeline(state, store, pipeline, personas_dir, provision=provision)
        )

        elapsed_sec = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Pipeline complete (terminal=%s, elapsed=%.1fs)",
            final_state.is_terminal,
            elapsed_sec,
        )

        _write_agentic_summary(run_dir, final_state, elapsed_sec)
        _write_final_notebook(run_dir, store, final_state)
        _write_learner_package(run_dir, store, final_state, topic, learner_profile)

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


def _write_agentic_summary(run_dir: Path, state, elapsed_sec: float) -> None:
    """Write SUMMARY.md with routing log for agentic pipeline."""
    if state.is_terminal and state.terminal_ok:
        status = "✓ Acceptable"
    elif state.is_terminal:
        status = "✗ Ended without an acceptable notebook"
    else:
        status = "✗ Incomplete"

    lines = ["# Agentic Pipeline Summary\n\n"]
    lines.append(f"**Status**: {status}\n")
    if state.terminal_reason:
        lines.append(f"**Reason**: {state.terminal_reason}\n")
    lines.append(f"**Elapsed**: {elapsed_sec:.1f} seconds\n")
    lines.append(f"**Iterations**: {state.iteration}\n\n")

    if state.degradations:
        lines.append("## Degradations\n\n")
        lines.append(
            "These stages fell back instead of producing real output — treat the "
            "result with suspicion:\n\n"
        )
        for deg in state.degradations:
            lines.append(f"- **{deg.stage.value}** ({deg.kind}): {deg.detail}\n")
        lines.append("\n")

    if state.routing_log:
        lines.append("## Routing Log\n\n")
        for decision in state.routing_log:
            lines.append(f"### Iteration {decision.iteration}\n")
            lines.append(f"- **From**: {decision.from_stage.value}\n")
            lines.append(f"- **To**: {decision.to_stage.value if decision.to_stage else 'END'}\n")
            lines.append(f"- **Classification**: {decision.classification}\n")
            lines.append(f"- **Reason**: {decision.reason}\n\n")

    (run_dir / "SUMMARY.md").write_text("".join(lines), encoding="utf-8")


def _write_final_notebook(run_dir: Path, store, state) -> None:
    """Write the deliverable lesson.ipynb.

    Preference order:
      1. The executed copy of the latest notebook (real cell outputs baked in),
         written by the executor as <execution_report>_executed.ipynb.
      2. The latest assembled (unexecuted) notebook from the CodeAuthor.
      3. An empty-but-valid notebook, so the file is always openable in Jupyter.
    """
    import nbformat

    from .pipeline.state import PipelineStage

    for output in reversed(state.outputs):
        if output.stage == PipelineStage.EXECUTOR:
            executed = run_dir / f"{output.artifact_name}_executed.ipynb"
            if executed.is_file():
                (run_dir / "lesson.ipynb").write_text(
                    executed.read_text(encoding="utf-8"), encoding="utf-8"
                )
                return
            break

    for output in reversed(state.outputs):
        if output.stage in (PipelineStage.CODE_AUTHOR, PipelineStage.CONTENT_REVISER):
            notebook_content = store.get(output.artifact_name).content
            (run_dir / "lesson.ipynb").write_text(notebook_content, encoding="utf-8")
            return

    empty = nbformat.writes(nbformat.v4.new_notebook())
    (run_dir / "lesson.ipynb").write_text(empty, encoding="utf-8")


def _write_learner_package(run_dir: Path, store, state, topic: str, learner_profile) -> None:
    """Write the self-contained deliverable (README.md + requirements.txt) from the
    latest lesson plan, so even a degraded agentic run ships something a learner can
    set up and open — not just a notebook (P6). Best-effort: never fail the run over
    packaging; a missing/unparseable plan still yields a usable README + empty deps."""
    import logging

    from .packaging import PackageContext, write_package
    from .pipeline.state import PipelineStage

    plan = ""
    for output in reversed(state.outputs):
        if output.stage == PipelineStage.PLANNER and store.has(output.artifact_name):
            plan = store.get(output.artifact_name).content
            break

    try:
        write_package(
            run_dir,
            plan,
            PackageContext(
                topic=topic,
                learner_name=learner_profile.name,
                learner_description=learner_profile.description,
            ),
        )
    except OSError as exc:
        logging.getLogger(__name__).warning("Failed to write learner package: %s", exc)


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


def _build_header(pipeline, profile_label: str) -> str:
    """A one-line, honest run header: advertise the real shape of the run, including
    that a revision pipeline may add bounded extra rounds beyond its base stages."""
    base = len(pipeline.stages)
    if pipeline.revision is not None:
        shape = (
            f"{base} base stages + up to {pipeline.revision.max_iterations} "
            "revision round(s)"
        )
    else:
        shape = f"{base} stage(s)"
    return f"▶ pipeline '{pipeline.name}' — {shape}\n  learner profile: {profile_label}\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forged",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build a lesson notebook from a topic")
    build.add_argument("--topic", required=True, help="The lesson topic or brief")
    build.add_argument(
        "--config", default=str(DEFAULT_CONFIG),
        help="Pipeline YAML (default: bundled review-loop). "
             "Run 'forged pipelines' to list bundled options.",
    )
    build.add_argument(
        "--learner-profile",
        type=Path,
        help="Path to learner_profile.yaml. Describes learner background, learning style, "
             "and material density. Copy from templates/examples/ or create your own. "
             "Uses sensible default if omitted.",
    )
    build.add_argument(
        "--topic-spec",
        type=Path,
        help="Path to topic_specification.yaml. Defines scope, learning objectives, "
             "prerequisites, and depth. Copy from templates/examples/ or create your own. "
             "Uses sensible default if omitted.",
    )
    build.add_argument(
        "--runs", default=str(Path.cwd() / "runs"),
        help="Root directory for run outputs (default: ./runs)",
    )
    # Internal: persona/system-prompt directory. Hidden — users should not change it.
    build.add_argument("--personas", default=str(DEFAULT_PERSONAS), help=argparse.SUPPRESS)

    sub.add_parser("pipelines", help="List the bundled pipeline configs")

    agentic = sub.add_parser("agentic", help="Run the agentic pipeline with agent iteration")
    agentic.add_argument(
        "--config", default=str(DEFAULT_CONFIG),
        help="Pipeline YAML used to resolve stage-specific model defaults for the "
             "agentic run (default: bundled review-loop).",
    )
    agentic.add_argument(
        "--topic", required=True,
        help="Lesson topic (e.g., 'Teach me how hash maps work')",
    )
    agentic.add_argument(
        "--run-dir", type=Path, required=True,
        help="Output directory for lesson notebook and metadata",
    )
    agentic.add_argument(
        "--learner-profile",
        type=Path,
        help="Path to learner_profile.yaml (background, learning style, material "
             "density). Copy from templates/examples/ or create your own. "
             "Uses a sensible default if omitted.",
    )
    agentic.add_argument(
        "--topic-spec",
        type=Path,
        help="Path to topic_specification.yaml (scope, objectives, prerequisites, "
             "depth). Copy from templates/examples/ or create your own. "
             "Uses a sensible default if omitted.",
    )
    agentic.add_argument(
        "--no-provision", action="store_true",
        help="Skip building a per-run virtualenv from the lesson's requirements and run "
             "on the base kernel instead. Provisioning is ON by default so the lesson's "
             "cells run for real; use this for a fast, offline run when the deps are "
             "already importable.",
    )
    agentic.add_argument(
        "--debug", action="store_true",
        help="Enable DEBUG logging (shows detailed pipeline activity)",
    )
    agentic.add_argument(
        "--personas", default=str(DEFAULT_PERSONAS), help=argparse.SUPPRESS
    )

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
    """Sensible defaults when no topic spec is provided."""
    return TopicSpecification(
        title=topic,
        scope="implementation",
        learning_objectives=[f"Understand {topic}"],
        prerequisites=[],
        constraints="",
        depth="intermediate",
        focus_areas=[topic],
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


if __name__ == "__main__":
    raise SystemExit(main())
