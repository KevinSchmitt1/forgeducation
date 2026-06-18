"""RevisorAgent — classifies quality and routes the pipeline to the next stage.

Persona: personas/reviser.md
Input artifacts: execution_report_v{N}.json, student_grade_report_v{N}.json
Output: revision_brief_v{N}.md (structured feedback for rerouted agents)
Output: state update with routing_log entry or is_terminal flag
Next stage: None (state.routing_log[-1].to_stage determines routing)

This agent is the only one that modifies routing_log.  It delegates to the
deterministic classify() + Router.route() stack — no LLM calls needed here.
When rerouting, writes revision_brief artifact with failure context for the
next agent to read and improve its output.
A RoutingBudget can be injected at construction for testing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from forged.artifacts import ArtifactStore

if TYPE_CHECKING:
    from forged.pipeline.structure import StructuralReport
from forged.pipeline.failure import (
    RUBRIC_DIMENSIONS,
    ExecutionReport,
    FailureCategory,
    GradeReport,
    RubricScores,
    classify,
)
from forged.pipeline.router import Router, RoutingBudget, RoutingRequest
from forged.pipeline.state import (
    Evidence,
    Location,
    LocationType,
    PipelineStage,
    PipelineState,
    Scope,
    Severity,
)

from . import Agent, AgentOutput

_LOG = logging.getLogger(__name__)


class RevisorAgent(Agent[AgentOutput]):
    """Reads signals from executor + student and routes the pipeline.

    Uses classify() and Router.route() deterministically — no LLM.
    A custom RoutingBudget can be injected to override defaults (useful in tests).
    """

    def __init__(
        self, personas_dir=None, llm_client=None, budget: RoutingBudget | None = None
    ) -> None:
        super().__init__(personas_dir=personas_dir, llm_client=llm_client)
        self._router = Router(budget=budget)

    def _load_persona(self) -> str:
        path = self.personas_dir / "reviser.md"
        return path.read_text(encoding="utf-8")

    def next_stage(self) -> PipelineStage | None:
        return None

    async def run(self, state: PipelineState, store: ArtifactStore) -> PipelineState:
        from forged.artifacts import Artifact

        exec_report = self._read_execution_report(state, store)
        grade_report = self._read_grade_report(state, store)
        grade_report = self._merge_reviewer_findings(state, store, grade_report)
        structural_report = self._assess_structure(state, store)
        classification = classify(
            exec_report, grade_report, structural_report=structural_report
        )
        request = RoutingRequest(
            state=state,
            classification=classification,
            evidence=list(grade_report.findings) if grade_report else [],
        )
        result = self._router.route(request)
        if result.should_terminate:
            is_acceptable = classification.category == FailureCategory.ACCEPTABLE
            return state.with_terminal(result.reason, ok=is_acceptable)
        if result.routing_decision is None:
            raise RuntimeError("Router returned non-terminal result with no routing_decision")
        if result.next_stage is None:
            raise RuntimeError("Router returned non-terminal result with no next_stage")

        brief = self._synthesize_revision_brief(
            exec_report, grade_report, classification, result.next_stage
        )
        brief_name = f"revision_brief_v{state.iteration}"
        store.put(Artifact(name=brief_name, kind="text", content=brief))
        _LOG.info(f"RevisorAgent: wrote {brief_name}; routing to {result.next_stage.value}")

        new_state = state.with_routing_decision(result.routing_decision)
        new_state = new_state.with_attempt(result.next_stage)
        return new_state.with_current_stage(result.next_stage)

    def _read_execution_report(
        self, state: PipelineState, store: ArtifactStore
    ) -> ExecutionReport | None:
        name = self._latest_artifact_name(state, PipelineStage.EXECUTOR, "execution_report")
        if not store.has(name):
            return None
        try:
            raw = json.loads(store.get(name).content)
        except json.JSONDecodeError:
            _LOG.warning("RevisorAgent: invalid execution report JSON in %s", name)
            return None
        return ExecutionReport(
            ok=raw.get("ok", True),
            failed_cells=raw.get("failed_cells", []),
            error_summary=raw.get("error_summary"),
        )

    def _read_grade_report(
        self, state: PipelineState, store: ArtifactStore
    ) -> GradeReport | None:
        name = self._latest_artifact_name(state, PipelineStage.STUDENT, "student_grade_report")
        if not store.has(name):
            return None
        try:
            raw = json.loads(store.get(name).content)
        except json.JSONDecodeError:
            _LOG.warning("RevisorAgent: invalid grade report JSON in %s", name)
            return None
        findings = self._findings_from_json(raw.get("findings", []), default_source="student")
        return GradeReport(
            quality_score=raw.get("quality_score", 0.0),
            rubric=self._coerce_rubric(raw.get("rubric")),
            graded=raw.get("graded", True),
            blockers=raw.get("blockers", []),
            findings=findings,
        )

    def _findings_from_json(
        self, raw_findings: object, default_source: str
    ) -> list[Evidence]:
        """Coerce a JSON findings list (student or reviewer) into Evidence objects.

        Tolerant of partial entries from real LLM output: an entry that is not a dict
        or lacks a description is skipped rather than crashing the routing loop. Shared
        by the student and reviewer readers so both critics' findings parse identically.
        """
        if not isinstance(raw_findings, list):
            return []
        findings: list[Evidence] = []
        for f in raw_findings:
            if not isinstance(f, dict) or not f.get("text"):
                continue
            location = f.get("location") or {}
            loc_type = self._coerce_location_type(location.get("type"))
            findings.append(
                Evidence(
                    source=f.get("source") or default_source,
                    severity=self._coerce_severity(f.get("severity")),
                    scope=self._coerce_scope(f.get("scope")),
                    location=Location(
                        type=loc_type,
                        cell_index=(
                            location.get("cell_index")
                            if loc_type == LocationType.CELL
                            else None
                        ),
                        label=location.get("label"),
                    ),
                    text=f["text"],
                )
            )
        return findings

    def _merge_reviewer_findings(
        self,
        state: PipelineState,
        store: ArtifactStore,
        grade_report: GradeReport | None,
    ) -> GradeReport | None:
        """Fold the Reviewer's findings into the grade report before classification.

        The Reviewer is the expert/correctness critic; its findings carry the same
        scope vocabulary as the student's, so merging them means a reviewer BLOCKER in
        `code` scope routes to the code author (TEST_FAILURE) and one in `plan`/
        `structure` scope triggers a replan — even when the lesson reads fine to the
        learner-student. The student's quality_score, rubric and graded flag are kept
        as-is: the reviewer is a findings critic, not a second scorer, so it never
        double-counts against the quality threshold.
        """
        reviewer_findings, reviewer_blockers = self._read_reviewer_report(state, store)
        if not reviewer_findings and not reviewer_blockers:
            return grade_report

        if grade_report is None:
            # Student produced no grade (e.g. it did not run). Carry the reviewer's
            # signal alone with a passing score, so only genuine reviewer blockers
            # route and an empty review does not masquerade as low quality.
            return GradeReport(
                quality_score=100.0,
                rubric=None,
                graded=True,
                blockers=list(reviewer_blockers),
                findings=reviewer_findings,
            )

        return replace(
            grade_report,
            findings=[*grade_report.findings, *reviewer_findings],
            blockers=[*grade_report.blockers, *reviewer_blockers],
        )

    def _read_reviewer_report(
        self, state: PipelineState, store: ArtifactStore
    ) -> tuple[list[Evidence], list[str]]:
        """Read the latest reviewer_report artifact as (findings, blockers).

        Returns empty lists when the reviewer did not run, its JSON is invalid, or it
        degraded (reviewed=False) — an absent review simply adds no findings.
        """
        name = self._latest_artifact_name(state, PipelineStage.REVIEWER, "reviewer_report")
        if not store.has(name):
            return [], []
        try:
            raw = json.loads(store.get(name).content)
        except json.JSONDecodeError:
            _LOG.warning("RevisorAgent: invalid reviewer report JSON in %s", name)
            return [], []
        findings = self._findings_from_json(raw.get("findings", []), default_source="reviewer")
        blockers = raw.get("blockers", [])
        if not isinstance(blockers, list):
            blockers = []
        return findings, blockers

    @staticmethod
    def _coerce_rubric(raw: object) -> RubricScores | None:
        """Rebuild RubricScores from the grade-report JSON when present and complete.

        The student already normalises the rubric to all five numeric dimensions
        (or null), so a partial/malformed rubric here is simply dropped rather
        than failing the read.
        """
        if not isinstance(raw, dict) or not all(
            isinstance(raw.get(d), (int, float)) and not isinstance(raw.get(d), bool)
            for d in RUBRIC_DIMENSIONS
        ):
            return None
        return RubricScores(**{d: float(raw[d]) for d in RUBRIC_DIMENSIONS})

    def _assess_structure(
        self, state: PipelineState, store: ArtifactStore
    ) -> StructuralReport | None:
        """Run the deterministic anti-hollow check on the executed notebook.

        Reads the executor's executed-with-outputs notebook from the run dir and
        assesses it. Returns None when the executed notebook is absent or
        unparseable (e.g. a mocked executor in tests) so the classifier simply
        skips the structural gate rather than crashing or false-failing.
        """
        from forged.executor import executed_notebook_filename
        from forged.pipeline.structure import assess_structure

        exec_name = self._latest_artifact_name(
            state, PipelineStage.EXECUTOR, "execution_report"
        )
        executed_path = store.run_dir / executed_notebook_filename(exec_name)
        if not executed_path.exists():
            return None
        try:
            return assess_structure(executed_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — gating must degrade, not crash
            _LOG.warning("RevisorAgent: could not assess notebook structure: %s", exc)
            return None

    def _latest_artifact_name(
        self, state: PipelineState, stage: PipelineStage, fallback_prefix: str
    ) -> str:
        for output in reversed(state.outputs):
            if output.stage == stage:
                return output.artifact_name
        return f"{fallback_prefix}_v{state.iteration}"

    def _synthesize_revision_brief(
        self,
        exec_report: ExecutionReport | None,
        grade_report: GradeReport | None,
        classification,
        next_stage: PipelineStage,
    ) -> str:
        """Create structured feedback artifact for rerouted agents.

        This brief tells the next agent (CodeAuthor or Planner) what failed
        and why it's being rerouted. Agents read this to improve their output.
        """
        lines = ["# Revision Brief\n"]
        lines.append(f"**Classification**: {classification.category.value}\n")
        lines.append(f"**Reason**: {classification.reason}\n")
        lines.append(f"**Next Stage**: {next_stage.value}\n\n")

        if exec_report:
            lines.append("## Execution Report\n")
            lines.append(f"- **Status**: {'✓ OK' if exec_report.ok else '✗ FAILED'}\n")
            if exec_report.failed_cells:
                failed = ", ".join(map(str, exec_report.failed_cells))
                lines.append(f"- **Failed Cells**: {failed}\n")
            if exec_report.error_summary:
                lines.append(f"- **Error**: {exec_report.error_summary}\n")
            lines.append("\n")

        # Only show a quality score when there is a real grade behind it. An
        # ungraded report (grader failed) carries a placeholder 0.0 that would
        # otherwise read as "scored zero" to the rerouted agent.
        if grade_report and grade_report.graded:
            lines.append("## Quality Report\n")
            lines.append(f"- **Score**: {grade_report.quality_score}/100\n")
            if grade_report.rubric is not None:
                r = grade_report.rubric
                lines.append(
                    "- **Rubric** (0–100): "
                    f"structure {r.structure:.0f}, "
                    f"explanation_depth {r.explanation_depth:.0f}, "
                    f"code_clarity {r.code_clarity:.0f}, "
                    f"correctness {r.correctness:.0f}, "
                    f"learner_fit {r.learner_fit:.0f}\n"
                )
            if grade_report.findings:
                lines.append("- **Key Findings**:\n")
                for finding in grade_report.findings[:5]:
                    loc = self._format_location(finding.location)
                    src = f" ({finding.source})" if finding.source else ""
                    lines.append(f"  - [{finding.severity}{src}] {loc}{finding.text}\n")
            lines.append("\n")

        lines.append("## Action Items\n")
        if next_stage == PipelineStage.CODE_AUTHOR:
            lines.append("- Fix the code failures listed above\n")
            lines.append("- Ensure all cells execute without error\n")
        elif next_stage == PipelineStage.PLANNER:
            lines.append("- Revise the lesson structure and learning objectives\n")
            lines.append("- Address the quality gaps identified above\n")
        elif next_stage == PipelineStage.CONTENT_REVISER:
            lines.append("- Rewrite the weak explanations flagged above into real teaching\n")
            lines.append("- Deepen explanation_depth and learner_fit; keep working code intact\n")

        return "".join(lines)

    @staticmethod
    def _format_location(location: Location) -> str:
        """Render a finding's anchor as a short prefix, e.g. 'cell 3 — '.

        Gives the rerouted agent a concrete place to look instead of a bare
        sentence. Returns '' for global findings that have no specific anchor.
        """
        if location.type == LocationType.CELL and location.cell_index is not None:
            return f"cell {location.cell_index} — "
        if location.label:
            return f"{location.label} — "
        return ""

    def _coerce_severity(self, raw: str | None) -> Severity:
        """Map the student persona's severity vocabulary onto Evidence severities.

        The persona emits BLOCKER/CONFUSING/NITPICK (the linear ledger's
        contract); the classifier expects BLOCKER/HIGH/MEDIUM/LOW. Coerce here
        so one persona file can serve both pipelines.
        """
        mapping: dict[str, Severity] = {
            "BLOCKER": "BLOCKER",
            "HIGH": "HIGH",
            "MEDIUM": "MEDIUM",
            "LOW": "LOW",
            "CONFUSING": "MEDIUM",
            "NITPICK": "LOW",
        }
        return mapping.get((raw or "").strip().upper(), "MEDIUM")

    def _coerce_scope(self, raw: str | None) -> Scope:
        """Normalize loose scope labels from real LLM output to classifier scopes.

        The classifier only acts on plan/structure (BLOCKER_STRUCTURE) and
        code (TEST_FAILURE); anything unrecognized becomes "unknown" rather
        than silently passing through an invalid value.
        """
        mapping: dict[str, Scope] = {
            "plan": "plan",
            "structure": "structure",
            "code": "code",
            "content": "content",
        }
        return mapping.get((raw or "").strip().lower(), "unknown")

    def _coerce_location_type(self, raw_type: str | None) -> LocationType:
        """Accept slightly looser external labels from LLM output.

        Real model responses sometimes emit notebook-level findings using
        `notebook` instead of the internal `artifact` enum label. Preserve the
        intent rather than crashing the revision loop on otherwise usable
        feedback.
        """
        mapping = {
            "cell": LocationType.CELL,
            "section": LocationType.SECTION,
            "lesson_structure": LocationType.LESSON_STRUCTURE,
            "artifact": LocationType.ARTIFACT,
            "notebook": LocationType.ARTIFACT,
            "global": LocationType.GLOBAL,
            "lesson": LocationType.GLOBAL,
        }
        return mapping.get((raw_type or "").strip().lower(), LocationType.GLOBAL)
