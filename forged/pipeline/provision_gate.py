"""Provisioning preflight — build the lesson's environment before the expensive stage.

The planner (gpt-5-mini) emits the ``requirements`` block, and the CodeAuthor (gpt-5)
writes the notebook. Provisioning used to run only inside the ExecutorAgent, i.e. after
the notebook already existed, so an environment pip could not build discarded the single
most expensive stage of the run. Both 2026-07-30 paid course runs died exactly that way
(docs/architecture/18-mode-selection-bias-and-run-honesty.md).

This module holds that attempt as one function so the graph can run it directly after the
planner *and* the executor can keep calling it. Because the venv cache is
content-addressed, the executor's later call for the same requirements is a marker-file
check — the preflight costs nothing extra on the happy path.

This is a timing change only. The gate enforces no package policy and refuses nothing the
plan asked for; it just moves *when* an unbuildable environment is discovered.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NamedTuple

from forged.artifacts import Artifact, ArtifactStore
from forged.executor import DEFAULT_KERNEL
from forged.pipeline.dependencies import extract_requirements
from forged.pipeline.state import Degradation, PipelineStage, PipelineState, StageOutput

logger = logging.getLogger(__name__)

#: Graph node name for the preflight. Only present when provisioning is enabled.
GATE_NODE = "provision_gate"


class Provisioned(NamedTuple):
    """Outcome of a provisioning attempt: the kernel to execute against, plus a terminal
    state when provisioning failed (in which case the caller must stop immediately)."""

    kernel: str
    terminal_state: PipelineState | None


def latest_plan_name(state: PipelineState) -> str | None:
    """Name of the most recent planner artifact, or None before the planner has run."""
    for output in reversed(state.outputs):
        if output.stage == PipelineStage.PLANNER:
            return output.artifact_name
    return None


def provision_for_state(
    state: PipelineState,
    store: ArtifactStore,
    cache_root: Path | None = None,
) -> Provisioned:
    """Provision a venv from the plan's requirements; pick the kernel to run against.

    Returns the kernel name (or the base kernel when no deps are needed) on success. On
    failure it records a Degradation, writes an honest failing execution report, and
    returns a *terminal* state — a missing runtime cannot be fixed by recoding or
    replanning, so the run ends honestly instead of looping or shipping a
    green-but-hollow notebook.
    """
    from forged.provisioning import provision_environment

    plan_name = latest_plan_name(state)
    plan = store.get(plan_name).content if plan_name and store.has(plan_name) else ""
    requirement_set = extract_requirements(plan)

    resolved_cache_root = cache_root or (store.run_dir.parent / ".venv-cache")
    result = provision_environment(requirement_set, cache_root=resolved_cache_root)

    if not result.ok:
        logger.warning("Provisioning failed: %s", result.error)
        return Provisioned(
            kernel=DEFAULT_KERNEL,
            terminal_state=_terminal_failure(state, store, result.error),
        )

    if result.cache_hit:
        logger.info("Provisioning cache hit: reusing kernel %s", result.kernel_name)
    elif result.kernel_name:
        logger.info("Provisioned new environment: kernel %s", result.kernel_name)
    return Provisioned(kernel=result.kernel_name or DEFAULT_KERNEL, terminal_state=None)


def _terminal_failure(
    state: PipelineState, store: ArtifactStore, error: str | None
) -> PipelineState:
    """Record the failure as an execution report + Degradation, and mark state terminal."""
    artifact_name = f"execution_report_v{state.iteration}"
    report = {"ok": False, "failed_cells": [], "error_summary": error}
    store.put(Artifact(name=artifact_name, kind="json", content=json.dumps(report)))
    new_state = state.with_output(
        StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
    ).with_degradation(
        Degradation(
            stage=PipelineStage.EXECUTOR,
            kind="provision_failed",
            detail=error or "environment provisioning failed",
        )
    )
    return new_state.with_terminal(f"Environment provisioning failed: {error}", ok=False)
