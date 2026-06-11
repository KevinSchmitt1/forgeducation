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

from forged.artifacts import Artifact, ArtifactStore
from forged.config import StageConfig, StageType
from forged.executor import ExecutorStage
from forged.pipeline.state import PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

logger = logging.getLogger(__name__)


class ExecutorAgent(Agent[AgentOutput]):
    """Executes the lesson notebook and produces a structured execution report.

    No LLM persona is required — execution is deterministic.  The persona
    attribute is set to an empty string via _load_persona().
    """

    def _load_persona(self) -> str:
        return ""

    def next_stage(self) -> PipelineStage:
        return PipelineStage.STUDENT

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
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
                report = self._execute_real(notebook_name, store, state)
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
        for output in reversed(state.outputs):
            if output.stage == PipelineStage.CODE_AUTHOR:
                return output.artifact_name
        return f"lesson_notebook_v{state.iteration}"

    def _execute_real(self, notebook_name: str, store: ArtifactStore, state: PipelineState) -> dict:
        """Execute notebook using real ExecutorStage; return ExecutionReport-compatible dict."""
        output_name = f"execution_report_v{state.iteration}"
        stage_config = StageConfig(
            name="executor",
            type=StageType.EXECUTOR,
            inputs=[notebook_name],
            output=output_name,
            output_kind="json",
            params={"timeout": 120, "kernel": "python3"},
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
