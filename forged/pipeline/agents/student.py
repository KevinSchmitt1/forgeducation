"""StudentAgent — grades the notebook as a learner and produces a GradeReport.

Persona: personas/student.md
Input artifacts: lesson_notebook_v{N}, execution_report_v{N}
Output artifact: student_grade_report_v{iteration}.json  (kind=json)
Next stage: None (Reviser reads the report and determines routing)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from forged.artifacts import Artifact, ArtifactStore
from forged.pipeline.failure import RUBRIC_DIMENSIONS, RubricScores
from forged.pipeline.state import Degradation, PipelineStage, PipelineState, StageOutput

from . import Agent, AgentOutput
from ._jsonparse import extract_json_candidate

_LOG = logging.getLogger(__name__)

# Required top-level keys for a usable grade report. rubric is optional so that a
# valid-but-rubric-less grade still counts as graded; a report missing any of
# these is treated as a failed assessment, not silently coerced to a score.
_REQUIRED_KEYS = {"quality_score", "blockers", "findings"}

_LOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["cell", "section", "lesson_structure", "artifact", "global"],
        },
        "cell_index": {"type": ["integer", "null"]},
        "label": {"type": ["string", "null"]},
    },
    "required": ["type", "cell_index", "label"],
    "additionalProperties": False,
}

_FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "severity": {"type": "string", "enum": ["BLOCKER", "CONFUSING", "NITPICK"]},
        "scope": {"type": "string", "enum": ["plan", "structure", "code", "content"]},
        "location": _LOCATION_SCHEMA,
        "text": {"type": "string"},
    },
    "required": ["source", "severity", "scope", "location", "text"],
    "additionalProperties": False,
}

STUDENT_GRADE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "student_grade_report",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "quality_score": {"type": "number", "minimum": 0, "maximum": 100},
                "rubric": {
                    "type": ["object", "null"],
                    "properties": {
                        "structure": {"type": "number", "minimum": 0, "maximum": 100},
                        "explanation_depth": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 100,
                        },
                        "code_clarity": {"type": "number", "minimum": 0, "maximum": 100},
                        "correctness": {"type": "number", "minimum": 0, "maximum": 100},
                        "learner_fit": {"type": "number", "minimum": 0, "maximum": 100},
                    },
                    "required": list(RUBRIC_DIMENSIONS),
                    "additionalProperties": False,
                },
                "verdict": {"type": "string"},
                "blockers": {"type": "array", "items": {"type": "string"}},
                "findings": {"type": "array", "items": _FINDING_SCHEMA},
            },
            "required": ["quality_score", "rubric", "verdict", "blockers", "findings"],
            "additionalProperties": False,
        },
    },
}


def _failed_report(reason: str) -> str:
    """A grade report that records the *absence* of an assessment.

    graded=False is the honest signal the classifier needs: it means the student
    could not judge the lesson, NOT that the lesson scored low. The score is 0.0
    only as a placeholder — the classifier ignores it when graded is False. This
    is the fix for the silent neutral-50 fallback that let a failed grader look
    like mediocre content and burn a no-op reviser lap.
    """
    return json.dumps(
        {
            "quality_score": 0.0,
            "graded": False,
            "rubric": None,
            "blockers": [],
            "findings": [],
            "error": reason[:300],
        }
    )


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
        artifact_name = f"student_grade_report_v{state.iteration}"
        degradation: Degradation | None = None
        try:
            response, graded = self._call_llm(state, store, user_msg, artifact_name)
            if not graded:
                # The specific reason (e.g. which keys were missing) lives in the
                # failed report's "error" field — surface it rather than a generic line.
                detail = json.loads(response).get(
                    "error", "Student response could not be parsed into a grade report"
                )
                _LOG.warning("StudentAgent could not parse a grade report: %s", detail)
                degradation = Degradation(
                    stage=PipelineStage.STUDENT, kind="grade_unparseable", detail=detail
                )
        except RuntimeError as exc:
            _LOG.warning("StudentAgent LLM call failed, marking grade as failed: %s", exc)
            response = _failed_report(str(exc))
            degradation = Degradation(
                stage=PipelineStage.STUDENT, kind="grade_failed", detail=str(exc)
            )
        store.put(Artifact(name=artifact_name, kind="json", content=response))
        output = StageOutput(
            stage=PipelineStage.STUDENT,
            artifact_name=artifact_name,
            iteration=state.iteration,
        )
        new_state = state.with_output(output)
        if degradation is not None:
            new_state = new_state.with_degradation(degradation)
        return new_state.with_current_stage(PipelineStage.REVISER)

    def _call_llm(
        self,
        state: PipelineState,
        store: ArtifactStore,
        user_msg: str,
        output_artifact: str,
    ) -> tuple[str, bool]:
        """Call the LLM and return (grade-report JSON, graded).

        graded is False when the response could not be parsed into a usable
        grade report — the caller records a degradation and the classifier
        treats the run as UNCLASSIFIABLE rather than poor content.
        """
        raw = self._complete_llm(
            stage_name=PipelineStage.STUDENT,
            state=state,
            store=store,
            user_msg=user_msg,
            input_artifacts=(
                self._latest_notebook_name(state),
                self._latest_execution_name(state),
            ),
            output_artifact=output_artifact,
            response_format=STUDENT_GRADE_RESPONSE_FORMAT,
        )
        return self._parse_grade_report(raw)

    def _parse_grade_report(self, raw: str) -> tuple[str, bool]:
        """Extract and validate the JSON grade report from the LLM response.

        Parses the whole (structured-output) response first, falling back to fence/brace
        extraction for prose-wrapped providers. On any parse error or missing required key
        the report is marked ungraded (graded=False) — an honest "could not assess", never
        a silent neutral score.

        Returns (json_string, graded).
        """
        # Structured output (response_format) returns pure JSON — parse the whole response
        # first; fence/brace extraction is only a fallback for prose-wrapped providers.
        candidate = extract_json_candidate(raw)

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return _failed_report("Could not parse JSON from student response"), False

        if not isinstance(parsed, dict):
            return _failed_report("Student response was not a JSON object"), False

        missing = _REQUIRED_KEYS - parsed.keys()
        if missing:
            return _failed_report(f"Grade report missing keys: {sorted(missing)}"), False

        # A successfully parsed report is, by definition, a real grade.
        parsed["graded"] = True
        rubric = self._normalize_rubric(parsed.get("rubric"))
        parsed["rubric"] = rubric
        # Derive the routing score from the rubric so the five concrete dimensions
        # — not a separate, possibly-inconsistent number the model emitted — drive
        # the quality threshold. Reports without a usable rubric keep the model's
        # own quality_score.
        if rubric is not None:
            parsed["quality_score"] = RubricScores(**rubric).composite()
        return json.dumps(parsed), True

    @staticmethod
    def _normalize_rubric(rubric: object) -> dict | None:
        """Keep the rubric only when every dimension is a real number in [0, 100].

        A grade without a usable rubric is still a valid grade (graded stays True);
        we simply drop a malformed rubric rather than fail the whole assessment.
        bool is excluded explicitly (it is a subclass of int) so a stray `true`
        cannot masquerade as the score 1.0.
        """
        if not isinstance(rubric, dict):
            return None

        def _is_score(value: object) -> bool:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0 <= value <= 100
            )

        if not all(_is_score(rubric.get(dim)) for dim in RUBRIC_DIMENSIONS):
            return None
        return {dim: float(rubric[dim]) for dim in RUBRIC_DIMENSIONS}

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
