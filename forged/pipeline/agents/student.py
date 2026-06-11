"""StudentAgent — grades the notebook as a learner and produces a GradeReport.

Persona: personas/student.md
Input artifacts: lesson_notebook_v{N}, execution_report_v{N}
Output artifact: student_grade_report_v{iteration}.json  (kind=json)
Next stage: None (Reviser reads the report and determines routing)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.state import PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

_LOG = logging.getLogger(__name__)

_NEUTRAL_REPORT = {"quality_score": 50.0, "blockers": [], "findings": []}


class StudentAgent(Agent[AgentOutput]):
    """Reviews the notebook from the learner's perspective and produces a grade.

    Reads the executed notebook and execution_report, then produces a JSON
    grade report with quality_score, blockers, and findings.
    """

    def __init__(self, personas_dir: Path | None = None, llm_client=None) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)

    def _load_persona(self) -> str:
        path = self.personas_dir / "student.md"
        return path.read_text(encoding="utf-8")

    def next_stage(self) -> PipelineStage | None:
        return None

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        user_msg = self._build_user_message(state, store)
        try:
            response = self._call_llm(user_msg)
        except RuntimeError as exc:
            _LOG.warning("StudentAgent LLM call failed, using neutral report: %s", exc)
            response = json.dumps(_NEUTRAL_REPORT)
        artifact_name = f"student_grade_report_v{state.iteration}"
        store.put(Artifact(name=artifact_name, kind="json", content=response))
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        return state.with_output(output).with_current_stage(PipelineStage.REVISER)

    def _call_llm(self, user_msg: str) -> str:
        """Call the LLM and return a parsed grade-report JSON string."""
        raw = self._llm_client.complete(self.persona, user_msg)
        return self._parse_grade_report(raw)

    def _parse_grade_report(self, raw: str) -> str:
        """Extract and validate the JSON grade report from the LLM response.

        Tries to find a trailing ```json block or a bare JSON object.  On any
        parse error or missing required keys the method gracefully degrades to
        a neutral report rather than crashing the pipeline.

        Returns a JSON string with quality_score, blockers, and findings.
        """
        # Try to extract a ```json ... ``` fence at the end of the response
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            candidate = fence_match.group(1).strip()
        else:
            # Try to find the last bare { ... } block in the response
            brace_match = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\})", raw, re.DOTALL)
            candidate = brace_match.group(1).strip() if brace_match else raw.strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            _LOG.warning(
                "StudentAgent: could not parse JSON from LLM response; using neutral report"
            )
            return json.dumps(_NEUTRAL_REPORT)

        if not isinstance(parsed, dict):
            _LOG.warning("StudentAgent: LLM returned non-dict JSON; using neutral report")
            return json.dumps(_NEUTRAL_REPORT)

        required = {"quality_score", "blockers", "findings"}
        missing = required - parsed.keys()
        if missing:
            _LOG.warning(
                "StudentAgent: grade report missing keys %s; using neutral report", missing
            )
            return json.dumps(_NEUTRAL_REPORT)

        return json.dumps(parsed)

    def _build_user_message(self, state: PipelineState, store: ArtifactStore) -> str:
        notebook_name = self._latest_notebook_name(state)
        exec_name = self._latest_execution_name(state)
        notebook_content = (
            self._render_notebook(store.get(notebook_name).content)
            if store.has(notebook_name)
            else "(no notebook)"
        )
        exec_content = (
            store.get(exec_name).content if store.has(exec_name) else "(no execution report)"
        )
        profile_content = store.get("profile").content if store.has("profile") else ""
        parts = [
            f"Notebook:\n{notebook_content}",
            f"Execution Report:\n{exec_content}",
        ]
        if profile_content:
            parts.append(f"Learner Profile:\n{profile_content}")
        return "\n\n".join(parts)

    def _render_notebook(self, content: str) -> str:
        """Show the notebook as an index-labelled listing, not raw .ipynb JSON.

        The indices match the executor's cell indices exactly, so the student's
        cell references line up with the execution report. Falls back to the
        raw content if the artifact is not parseable nbformat.
        """
        from forged.notebook import render_indexed

        try:
            return render_indexed(content)
        except Exception:  # noqa: BLE001 — grading should degrade, not crash
            _LOG.warning("StudentAgent: notebook artifact is not valid nbformat; using raw content")
            return content

    def _latest_notebook_name(self, state: PipelineState) -> str:
        for output in reversed(state.outputs):
            if output.stage == PipelineStage.CODE_AUTHOR:
                return output.artifact_name
        return f"lesson_notebook_v{state.iteration}"

    def _latest_execution_name(self, state: PipelineState) -> str:
        for output in reversed(state.outputs):
            if output.stage == PipelineStage.EXECUTOR:
                return output.artifact_name
        return f"execution_report_v{state.iteration}"
