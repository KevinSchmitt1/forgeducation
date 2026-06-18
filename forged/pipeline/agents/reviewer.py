"""ReviewerAgent — an expert/SME critic that judges correctness and teaching quality.

Persona: personas/reviewer.md
Input artifacts: lesson_notebook_v{N}, execution_report_v{N}
Output artifact: reviewer_report_v{iteration}.json  (kind=json)
Next stage: REVISER (which merges reviewer + student findings before classifying)

The Reviewer is the second critic in the agentic pipeline. Unlike the Student — who
inhabits the learner profile and judges "could I follow this?" — the Reviewer does NOT
inhabit the profile; it judges objective correctness (wrong APIs, misleading output,
prose that contradicts the real result) and instructional soundness. Its findings carry
a `scope`, so a correctness BLOCKER (scope=code) routes the notebook back to the code
author even when the lesson reads fine to the learner.

Runs on the cheap stage model (gpt-5-mini by config) — one extra critic call per grading
lap, bounded by the loop budgets, so the second critic does not blow up cost.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.state import Degradation, PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput

_LOG = logging.getLogger(__name__)

# A usable reviewer report must at least carry a findings list. blockers is optional
# (an empty review is valid — the notebook may simply be correct).
_REQUIRED_KEYS = {"findings"}


def _failed_report(reason: str) -> str:
    """A reviewer report that records the *absence* of a review.

    reviewed=False is the honest signal: the reviewer could not assess the notebook,
    NOT that it found nothing. The Reviser treats an absent review as "no extra
    findings" and falls back to the student's grade alone — a failed reviewer never
    fabricates blockers or silently suppresses the student's signal.
    """
    return json.dumps(
        {
            "reviewed": False,
            "blockers": [],
            "findings": [],
            "error": reason[:300],
        }
    )


class ReviewerAgent(Agent[AgentOutput]):
    """Reviews the notebook as an expert and produces a findings report.

    Reads the executed notebook and execution_report, then produces a JSON report
    with blockers and structured findings (each carrying a scope used for routing).
    """

    def __init__(self, personas_dir: Path | None = None, llm_client=None) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)

    def _load_persona(self) -> str:
        path = self.personas_dir / "reviewer.md"
        return path.read_text(encoding="utf-8")

    def next_stage(self) -> PipelineStage:
        return PipelineStage.REVISER

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        user_msg = self._build_user_message(state, store)
        artifact_name = f"reviewer_report_v{state.iteration}"
        degradation: Degradation | None = None
        try:
            response, reviewed = self._call_llm(state, store, user_msg, artifact_name)
            if not reviewed:
                detail = json.loads(response).get(
                    "error", "Reviewer response could not be parsed into a findings report"
                )
                _LOG.warning("ReviewerAgent could not parse a review: %s", detail)
                degradation = Degradation(
                    stage=PipelineStage.REVIEWER, kind="review_unparseable", detail=detail
                )
        except RuntimeError as exc:
            _LOG.warning("ReviewerAgent LLM call failed, marking review as failed: %s", exc)
            response = _failed_report(str(exc))
            degradation = Degradation(
                stage=PipelineStage.REVIEWER, kind="review_failed", detail=str(exc)
            )
        store.put(Artifact(name=artifact_name, kind="json", content=response))
        output = StageOutput(
            stage=PipelineStage.REVIEWER,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        new_state = state.with_output(output)
        if degradation is not None:
            new_state = new_state.with_degradation(degradation)
        return new_state.with_current_stage(self.next_stage())

    def _call_llm(
        self,
        state: PipelineState,
        store: ArtifactStore,
        user_msg: str,
        output_artifact: str,
    ) -> tuple[str, bool]:
        """Call the LLM and return (review-report JSON, reviewed)."""
        raw = self._complete_llm(
            stage_name=PipelineStage.REVIEWER,
            state=state,
            store=store,
            user_msg=user_msg,
            input_artifacts=(
                self._latest_notebook_name(state),
                self._latest_execution_name(state),
            ),
            output_artifact=output_artifact,
        )
        return self._parse_review(raw)

    def _parse_review(self, raw: str) -> tuple[str, bool]:
        """Extract and validate the JSON review from the LLM response.

        Tries a trailing ```json block, then a bare JSON object. On any parse error or
        missing required key the report is marked unreviewed (reviewed=False) — an honest
        "could not assess", never fabricated findings.

        Returns (json_string, reviewed).
        """
        fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if fence_match:
            candidate = fence_match.group(1).strip()
        else:
            brace_match = re.search(r"(\{.*\})", raw, re.DOTALL)
            candidate = brace_match.group(1).strip() if brace_match else raw.strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return _failed_report("Could not parse JSON from reviewer response"), False

        if not isinstance(parsed, dict):
            return _failed_report("Reviewer response was not a JSON object"), False

        missing = _REQUIRED_KEYS - parsed.keys()
        if missing:
            return _failed_report(f"Review missing keys: {sorted(missing)}"), False

        parsed["reviewed"] = True
        parsed.setdefault("blockers", [])
        return json.dumps(parsed), True

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
        parts = [
            f"Notebook:\n{notebook_content}",
            f"Execution Report:\n{exec_content}",
        ]
        return self._context_prefix(store) + "\n\n".join(parts)

    def _render_notebook(self, content: str) -> str:
        """Show the notebook as an index-labelled listing, matching the executor's
        cell indices so the reviewer's cell references line up with the student's."""
        from forged.notebook import render_indexed

        try:
            return render_indexed(content)
        except Exception:  # noqa: BLE001 — reviewing should degrade, not crash
            _LOG.warning("ReviewerAgent: notebook artifact is not valid nbformat; using raw content")
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
