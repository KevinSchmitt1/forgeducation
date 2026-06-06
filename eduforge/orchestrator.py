"""Orchestrator — runs the stages of a pipeline in order.

Responsibilities, kept deliberately small:
  1. Create a fresh run directory and seed it with the user's brief.
  2. Dispatch each stage to the right runner (LLM agent or executor).
  3. Pass artifacts forward via the store and record the manifest.

When a revision policy is configured, the linear pipeline is followed by a bounded
revision loop that keeps re-running the current best notebook until it is good
enough, progress stalls, or the iteration budget is exhausted.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .agent import LLMAgent
from .artifacts import Artifact, ArtifactStore
from .config import PipelineConfig, RevisionPolicy, StageConfig, StageType
from .executor import ExecutorStage, executed_notebook_filename
from .gate import CandidateResult, GateDecision, evaluate_candidates
from .ledger import IssueLedger, parse_findings
from .report import build_summary

# Files a successful run keeps; everything else is pruned as intermediate plumbing.
DELIVERABLE_NOTEBOOK = "lesson.ipynb"
SUMMARY_FILE = "SUMMARY.md"
MANIFEST_FILE = "manifest.json"
RETAINED_FILES = {DELIVERABLE_NOTEBOOK, SUMMARY_FILE, MANIFEST_FILE}


class Orchestrator:
    """Drives one pipeline from a brief to a finished run directory."""

    def __init__(
        self,
        pipeline: PipelineConfig,
        personas_dir: Path,
        runs_root: Path,
        runner_factory: Callable[[StageConfig], object] | None = None,
    ):
        self._pipeline = pipeline
        self._personas_dir = personas_dir
        self._runs_root = runs_root
        self._runner_factory = runner_factory or self._build_runner
        # Per-run state, reset at the top of run():
        self._last_run_dir: Path | None = None  # exposed so the CLI can point at debug files
        self._timings: dict[str, float] = {}     # stage name -> wall-clock seconds

    @property
    def last_run_dir(self) -> Path | None:
        """The most recent run directory, set as soon as it is created — available even
        when the run later fails, so callers can point a user at the debug files."""
        return self._last_run_dir

    def run(
        self,
        brief: str,
        profile: str,
        profile_label: str = "profile",
        on_stage=None,
    ) -> ArtifactStore:
        """Execute every stage and return the populated store.

        `brief` is the lesson topic; `profile` is the target learner's prior
        knowledge + environment. Both are seeded before any stage runs.
        `on_stage` is an optional callback (stage_name, status, detail) for
        progress reporting — the CLI uses it to stream a live status line.
        """
        store = ArtifactStore.create(self._runs_root, self._pipeline.name)
        self._last_run_dir = store.run_dir
        self._timings = {}
        store.put(Artifact(name="brief", kind="text", content=brief))
        store.put(Artifact(name="profile", kind="text", content=profile))

        for stage in self._pipeline.stages:
            _run_stage(
                stage,
                store,
                self._runner_factory,
                self._pipeline.name,
                on_stage,
                self._timings,
            )

        runtime_pipeline = self._pipeline
        if self._pipeline.revision is not None:
            runtime_pipeline = self._revise_loop(store, on_stage)

        self._finalize(store, brief, profile_label, runtime_pipeline)
        return store

    def _finalize(
        self,
        store: ArtifactStore,
        brief: str,
        profile_label: str,
        pipeline: PipelineConfig,
    ) -> None:
        """On success: pick the notebook the gate accepts, write it + SUMMARY.md, then
        prune the intermediate plumbing so the run dir holds only human-facing files."""
        revision = pipeline.revision
        decision = evaluate_candidates(
            pipeline,
            store,
            min_quality=revision.min_quality_score if revision else 90,
        )

        if revision is not None and decision.crucial_open:
            # Hard fail, but leave the human something to read: write a SUMMARY.md
            # (its verdict renders the crucial-open state) and keep every debug file.
            store.write_file(
                SUMMARY_FILE,
                build_summary(pipeline, store, brief, profile_label, decision, self._timings),
            )
            store.write_manifest(
                pipeline.name,
                extra={
                    "status": "failed",
                    "failed_stage": "revision_loop",
                    "error": "Revision loop exhausted with a crucial issue still open",
                    "gate": _gate_manifest(decision),
                    **self._run_meta(),
                },
            )
            raise RuntimeError("Revision loop exhausted with a crucial issue still open")

        store.write_file(DELIVERABLE_NOTEBOOK, self._deliverable_notebook(store, decision))
        store.write_file(
            SUMMARY_FILE,
            build_summary(pipeline, store, brief, profile_label, decision, self._timings),
        )
        removed = store.finalize(RETAINED_FILES)
        store.write_manifest(
            pipeline.name,
            extra={
                "status": "completed",
                "retained": sorted(RETAINED_FILES),
                "pruned": sorted(removed),
                "gate": _gate_manifest(decision),
                **self._run_meta(),
            },
        )

    def _run_meta(self) -> dict:
        """Timing facts recorded in every manifest, for cost/latency visibility."""
        return {
            "timings": dict(self._timings),
            "total_seconds": round(sum(self._timings.values()), 3),
        }

    def _deliverable_notebook(self, store: ArtifactStore, decision: GateDecision) -> str:
        """The notebook a human should open: the executed-with-outputs notebook of the
        version the gate accepted, or the last assembled notebook if none ran."""
        if decision.chosen is not None:
            return store.read_file(
                executed_notebook_filename(decision.chosen.candidate.report)
            )
        for stage in reversed(self._pipeline.stages):
            if stage.output_kind == "notebook" and store.has(stage.output):
                return store.get(stage.output).content
        raise RuntimeError("Pipeline produced no notebook to deliver")

    def _build_runner(self, stage):
        """Map a stage to its runner. New non-LLM stage types slot in here."""
        if stage.type is StageType.EXECUTOR:
            return ExecutorStage(stage)
        return LLMAgent(stage, self._pipeline, self._personas_dir)

    def _revise_loop(self, store: ArtifactStore, on_stage) -> PipelineConfig:
        """Run the bounded revision loop and return the runtime pipeline."""
        policy = self._pipeline.revision
        if policy is None:
            return self._pipeline

        runtime_stages = list(self._pipeline.stages)
        runtime_pipeline = self._pipeline
        ledger = IssueLedger()

        decision = evaluate_candidates(
            runtime_pipeline,
            store,
            min_quality=policy.min_quality_score,
        )
        current_result = decision.chosen
        if current_result is None:
            raise RuntimeError("Revision loop expected a baseline notebook candidate")
        _append_ledger_entry(ledger, "baseline", current_result, store)

        for iteration in range(1, policy.max_iterations + 1):
            if current_result.accepted:
                break

            ledger_artifact = f"issue_ledger__i{iteration}"
            store.put(Artifact(name=ledger_artifact, kind="text", content=ledger.render()))

            revision_stages = self._build_revision_stages(
                policy=policy,
                iteration=iteration,
                notebook_name=current_result.candidate.notebook,
                ledger_name=ledger_artifact,
            )

            for stage in revision_stages:
                _run_stage(
                    stage,
                    store,
                    self._runner_factory,
                    self._pipeline.name,
                    on_stage,
                    self._timings,
                )

            runtime_stages.extend(revision_stages)
            runtime_pipeline = _pipeline_with_stages(self._pipeline, runtime_stages)
            decision = evaluate_candidates(
                runtime_pipeline,
                store,
                min_quality=policy.min_quality_score,
            )
            new_result = _result_for_report(decision, revision_stages[1].output)
            if new_result is None:
                raise RuntimeError("Revision loop failed to evaluate the new notebook")

            _append_ledger_entry(ledger, f"iteration {iteration}", new_result, store)

            # Spend the whole iteration budget on a stuck crucial issue: only bail early
            # when the revision is *strictly worse* than the current best. A tie (e.g. a
            # BLOCKER unchanged at rank (0, 0)) keeps iterating so the reviser gets more
            # attempts — keep-best still prevents a regression from ever shipping.
            if policy.require_progress and _rank(new_result) < _rank(current_result):
                break

            current_result = decision.chosen or current_result
            if current_result.accepted:
                break

        return runtime_pipeline

    def _build_revision_stages(
        self,
        policy: RevisionPolicy,
        iteration: int,
        notebook_name: str,
        ledger_name: str,
    ) -> list[StageConfig]:
        """Create the reviser/executor/critic stages for one iteration."""
        notebook_output = f"revised_notebook__i{iteration}"
        report_output = f"revised_execution_report__i{iteration}"
        reviser_model = _latest_notebook_model(self._pipeline)

        stages: list[StageConfig] = [
            StageConfig(
                name=f"reviser__i{iteration}",
                type=StageType.LLM,
                persona=policy.reviser,
                # 'brief' anchors the reviser to the original topic so revisions don't drift.
                inputs=["brief", notebook_name, ledger_name, "profile"],
                output=notebook_output,
                output_kind="notebook",
                model=reviser_model,
            ),
            StageConfig(
                name=f"executor_revised__i{iteration}",
                type=StageType.EXECUTOR,
                inputs=[notebook_output],
                output=report_output,
                params={**policy.executor_params},
            ),
        ]
        for critic in policy.critics:
            critic_name = Path(critic).stem
            stages.append(
                StageConfig(
                    name=f"{critic_name}__i{iteration}",
                    type=StageType.LLM,
                    persona=critic,
                    inputs=[notebook_output, report_output, "profile"],
                    output=f"{critic_name}_feedback__i{iteration}",
                    output_kind="text",
                )
            )
        return stages


def _run_stage(
    stage: StageConfig,
    store: ArtifactStore,
    runner_factory,
    pipeline_name: str,
    on_stage,
    timings: dict[str, float] | None = None,
) -> None:
    _notify(on_stage, stage.name, "start", stage.type.value)
    started = time.perf_counter()
    try:
        runner = runner_factory(stage)
        artifact = runner.run(store)
    except Exception as exc:  # noqa: BLE001 — record, then halt the run
        _notify(on_stage, stage.name, "error", str(exc))
        store.write_manifest(
            pipeline_name,
            extra={"status": "failed", "failed_stage": stage.name, "error": str(exc)},
        )
        raise
    elapsed = time.perf_counter() - started
    if timings is not None:
        timings[stage.name] = round(elapsed, 3)
    _notify(on_stage, stage.name, "done", f"{artifact.filename}  ({elapsed:.1f}s)")


def _notify(callback, stage_name: str, status: str, detail: str) -> None:
    if callback is not None:
        callback(stage_name, status, detail)


def _gate_manifest(decision: GateDecision) -> dict:
    """Record the acceptance gate's decision for the run's audit trail."""
    chosen = decision.chosen
    scores = [result.quality_score for result in decision.results]
    shipped_index = (
        next(
            (i for i, result in enumerate(decision.results, start=1) if result == chosen),
            None,
        )
        if chosen is not None
        else None
    )
    return {
        "satisfied": decision.gate_satisfied,
        "crucial_open": decision.crucial_open,
        "iterations": len(decision.results),
        "quality_scores": scores,
        "delivered": chosen.candidate.notebook if chosen else None,
        "delivered_quality": chosen.quality_score if chosen else None,
        "delivered_iteration": shipped_index,
        "candidates": [
            {
                "notebook": result.candidate.notebook,
                "executed_ok": result.executed_ok,
                "has_blocker": result.has_blocker,
                "quality_score": result.quality_score,
                "crucial": result.crucial,
                "accepted": result.accepted,
            }
            for result in decision.results
        ],
    }


def _pipeline_with_stages(pipeline: PipelineConfig, stages: list[StageConfig]) -> PipelineConfig:
    return PipelineConfig.model_construct(
        name=pipeline.name,
        defaults=pipeline.defaults,
        stages=stages,
        revision=pipeline.revision,
    )


def _result_for_report(decision: GateDecision, report_name: str) -> CandidateResult | None:
    for result in decision.results:
        if result.candidate.report == report_name:
            return result
    return None


def _append_ledger_entry(
    ledger: IssueLedger, label: str, result: CandidateResult, store: ArtifactStore
) -> None:
    findings = tuple(
        finding
        for feedback in result.candidate.feedbacks
        if store.has(feedback)
        for finding in parse_findings(store.get(feedback).content)
    )
    ledger.add(
        label=label,
        notebook=result.candidate.notebook,
        report=result.candidate.report,
        executed_ok=result.executed_ok,
        quality_score=result.quality_score,
        findings=findings,
    )


def _latest_notebook_model(pipeline: PipelineConfig):
    for stage in reversed(pipeline.stages):
        if stage.output_kind == "notebook":
            return pipeline.resolved_model(stage)
    return None


def _rank(result: CandidateResult) -> tuple[int, int]:
    return (0 if result.crucial else 1, result.quality_score)
