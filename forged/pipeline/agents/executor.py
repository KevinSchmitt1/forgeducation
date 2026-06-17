"""ExecutorAgent — runs the notebook and captures a structured execution report.

Persona: none (deterministic execution; no LLM needed)
Input artifacts: lesson_notebook_v{N}.ipynb  (reads latest from outputs)
Output artifact: execution_report_v{iteration}.json  (kind=json)
Next stage: STUDENT

Phase 7: Wired to real forged.executor.ExecutorStage. Detects actual notebook
execution failures and produces detailed cell-level reports.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import NamedTuple

from forged.artifacts import Artifact, ArtifactStore
from forged.config import StageConfig, StageType
from forged.executor import DEFAULT_KERNEL, ExecutorStage
from forged.pipeline.dependencies import extract_requirements
from forged.pipeline.state import Degradation, PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

logger = logging.getLogger(__name__)


class _Provisioned(NamedTuple):
    """Result of the provisioning step: the kernel to execute against, plus a terminal
    state when provisioning failed (in which case run() returns it immediately)."""

    kernel: str
    terminal_state: PipelineState | None


class ExecutorAgent(Agent[AgentOutput]):
    """Executes the lesson notebook and produces a structured execution report.

    No LLM persona is required — execution is deterministic. The persona attribute
    is set to an empty string via _load_persona().

    When ``provision`` is True (the CLI default; D1), the agent first builds/reuses a
    per-run venv from the plan's requirements and runs the notebook against that kernel,
    so a lesson's cells run for real instead of skipping behind dependency guards. If
    essential deps cannot be provisioned the run terminates honestly — never a
    green-but-hollow notebook. ``provision`` defaults to False so unit/integration tests
    and the graph builder opt in explicitly.
    """

    def __init__(
        self,
        personas_dir: Path | None = None,
        llm_client=None,
        provision: bool = False,
        cache_root: Path | None = None,
    ) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)
        self._provision = provision
        self._cache_root = cache_root

    def _load_persona(self) -> str:
        return ""

    def next_stage(self) -> PipelineStage:
        return PipelineStage.STUDENT

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        kernel = DEFAULT_KERNEL
        if self._provision:
            provisioned = self._provision_kernel(state, store)
            if provisioned.terminal_state is not None:
                return provisioned.terminal_state
            kernel = provisioned.kernel

        notebook_name = self._latest_notebook_name(state)
        if not store.has(notebook_name):
            # Honest failure, not fabricated success: a missing notebook means
            # nothing was executed, and the classifier must see that.
            logger.warning(f"Notebook artifact {notebook_name} not found; reporting failure")
            report = {
                "ok": False,
                "failed_cells": [],
                "error_summary": f"Notebook artifact '{notebook_name}' was never produced",
            }
        else:
            try:
                report = self._execute_real(notebook_name, store, state, kernel)
            except Exception as exc:
                logger.exception(f"Executor failed: {exc}")
                return state.with_terminal(f"Executor error: {exc}")

        artifact_name = f"execution_report_v{state.iteration}"
        store.put(Artifact(name=artifact_name, kind="json", content=json.dumps(report)))
        output = StageOutput(
            stage=PipelineStage.EXECUTOR,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(self.next_stage())

    def _latest_notebook_name(self, state: PipelineState) -> str:
        # Either notebook-producing stage may have written the latest notebook:
        # the code author on the first/recode pass, or the content reviser on a
        # CONTENT_QUALITY rewrite. Execute whichever ran most recently.
        notebook_stages = (PipelineStage.CODE_AUTHOR, PipelineStage.CONTENT_REVISER)
        for output in reversed(state.outputs):
            if output.stage in notebook_stages:
                return output.artifact_name
        return f"lesson_notebook_v{state.iteration}"

    def _latest_plan_name(self, state: PipelineState) -> str | None:
        for output in reversed(state.outputs):
            if output.stage == PipelineStage.PLANNER:
                return output.artifact_name
        return None

    def _provision_kernel(self, state: PipelineState, store: ArtifactStore) -> _Provisioned:
        """Provision a venv from the plan's requirements; pick the kernel to run against.

        Returns the kernel name (or the base kernel when no deps are needed) on success.
        On provisioning failure it records a Degradation, writes an honest failing
        execution report, and returns a *terminal* state — a missing runtime cannot be
        fixed by recoding or replanning, so the run ends honestly instead of looping or
        shipping a green-but-hollow notebook.
        """
        from forged.provisioning import provision_environment

        plan_name = self._latest_plan_name(state)
        plan = store.get(plan_name).content if plan_name and store.has(plan_name) else ""
        requirement_set = extract_requirements(plan)

        cache_root = self._cache_root or (store.run_dir.parent / ".venv-cache")
        result = provision_environment(requirement_set, cache_root=cache_root)

        if not result.ok:
            logger.warning("Provisioning failed: %s", result.error)
            artifact_name = f"execution_report_v{state.iteration}"
            report = {"ok": False, "failed_cells": [], "error_summary": result.error}
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
                    detail=result.error or "environment provisioning failed",
                )
            )
            return _Provisioned(
                kernel=DEFAULT_KERNEL,
                terminal_state=new_state.with_terminal(
                    f"Environment provisioning failed: {result.error}", ok=False
                ),
            )

        if result.cache_hit:
            logger.info("Provisioning cache hit: reusing kernel %s", result.kernel_name)
        elif result.kernel_name:
            logger.info("Provisioned new environment: kernel %s", result.kernel_name)
        return _Provisioned(kernel=result.kernel_name or DEFAULT_KERNEL, terminal_state=None)

    def _execute_real(
        self, notebook_name: str, store: ArtifactStore, state: PipelineState, kernel: str
    ) -> dict:
        """Execute notebook using real ExecutorStage; return ExecutionReport-compatible dict."""
        output_name = f"execution_report_v{state.iteration}"
        stage_config = StageConfig(
            name="executor",
            type=StageType.EXECUTOR,
            inputs=[notebook_name],
            output=output_name,
            output_kind="json",
            params={"timeout": 120, "kernel": kernel},
        )
        executor_stage = ExecutorStage(stage_config)
        result_artifact = executor_stage.run(store)
        result_dict = json.loads(result_artifact.content)

        failed_cells = [
            cell["cell_index"]
            for cell in result_dict.get("cells", [])
            if cell.get("status") == "error"
        ]
        error_summary = None
        if failed_cells and result_dict.get("cells"):
            for cell in result_dict["cells"]:
                if cell.get("status") == "error":
                    error_summary = cell.get("error")
                    break

        return {
            "ok": result_dict.get("ok", False),
            "failed_cells": failed_cells,
            "error_summary": error_summary,
        }
