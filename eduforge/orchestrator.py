"""Orchestrator — runs the stages of a pipeline in order.

Responsibilities, kept deliberately small:
  1. Create a fresh run directory and seed it with the user's brief.
  2. Dispatch each stage to the right runner (LLM agent or executor).
  3. Pass artifacts forward via the store and record the manifest.

The pipeline is a linear list for now. A DAG/branching model can replace this loop
later without changing the stage or artifact contracts.
"""

from __future__ import annotations

from pathlib import Path

from .agent import LLMAgent
from .artifacts import Artifact, ArtifactStore
from .config import PipelineConfig, StageType
from .executor import ExecutorStage, executed_notebook_filename
from .gate import GateDecision, evaluate_candidates
from .report import build_summary

# Files a successful run keeps; everything else is pruned as intermediate plumbing.
DELIVERABLE_NOTEBOOK = "lesson.ipynb"
SUMMARY_FILE = "SUMMARY.md"
MANIFEST_FILE = "manifest.json"
RETAINED_FILES = {DELIVERABLE_NOTEBOOK, SUMMARY_FILE, MANIFEST_FILE}


class Orchestrator:
    """Drives one pipeline from a brief to a finished run directory."""

    def __init__(self, pipeline: PipelineConfig, personas_dir: Path, runs_root: Path):
        self._pipeline = pipeline
        self._personas_dir = personas_dir
        self._runs_root = runs_root

    def run(self, brief: str, profile: str, profile_label: str = "profile",
            on_stage=None) -> ArtifactStore:
        """Execute every stage and return the populated store.

        `brief` is the lesson topic; `profile` is the target learner's prior
        knowledge + environment. Both are seeded before any stage runs.
        `on_stage` is an optional callback (stage_name, status, detail) for
        progress reporting — the CLI uses it to stream a live status line.
        """
        store = ArtifactStore.create(self._runs_root, self._pipeline.name)
        store.put(Artifact(name="brief", kind="text", content=brief))
        store.put(Artifact(name="profile", kind="text", content=profile))

        for stage in self._pipeline.stages:
            _notify(on_stage, stage.name, "start", stage.type.value)
            try:
                runner = self._build_runner(stage)
                artifact = runner.run(store)
            except Exception as exc:  # noqa: BLE001 — record, then halt the run
                _notify(on_stage, stage.name, "error", str(exc))
                # Failed runs keep ALL files for debugging — no pruning.
                store.write_manifest(
                    self._pipeline.name,
                    extra={"status": "failed", "failed_stage": stage.name,
                           "error": str(exc)},
                )
                raise
            _notify(on_stage, stage.name, "done", artifact.filename)

        self._finalize(store, brief, profile_label)
        return store

    def _finalize(self, store: ArtifactStore, brief: str, profile_label: str) -> None:
        """On success: pick the notebook the gate accepts, write it + SUMMARY.md, then
        prune the intermediate plumbing so the run dir holds only human-facing files."""
        decision = evaluate_candidates(self._pipeline, store)
        store.write_file(DELIVERABLE_NOTEBOOK, self._deliverable_notebook(store, decision))
        store.write_file(
            SUMMARY_FILE,
            build_summary(self._pipeline, store, brief, profile_label, decision),
        )
        removed = store.finalize(RETAINED_FILES)
        store.write_manifest(
            self._pipeline.name,
            extra={"status": "completed", "retained": sorted(RETAINED_FILES),
                   "pruned": sorted(removed), "gate": _gate_manifest(decision)},
        )

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


def _notify(callback, stage_name: str, status: str, detail: str) -> None:
    if callback is not None:
        callback(stage_name, status, detail)


def _gate_manifest(decision: GateDecision) -> dict:
    """Record the acceptance gate's decision for the run's audit trail."""
    chosen = decision.chosen
    return {
        "satisfied": decision.gate_satisfied,
        "crucial_open": decision.crucial_open,
        "delivered": chosen.candidate.notebook if chosen else None,
        "delivered_quality": chosen.quality_score if chosen else None,
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
