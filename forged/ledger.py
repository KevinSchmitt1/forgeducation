"""Issue findings — parsing and a graded quality score.

Critics (student, reviewer) emit findings in a shared format:
`[SEVERITY] cell N — issue`, where SEVERITY is BLOCKER, CONFUSING, or NITPICK.

This module turns that free text into structured findings and a single, graded
**quality score** (0–100). The design choice — discussed and agreed — is that
teaching quality is *graded*, not binary: a notebook with a couple of minor nits is
"good enough" to ship, whereas a real lecturer would never let a crucial error pass.
So BLOCKERs dominate the score (and are also treated as a hard floor by the gate),
while CONFUSING/NITPICK only chip away at it.

Counting severities is robust; matching whether two findings are "the same issue"
across notebook versions is NOT attempted here (LLM phrasing varies) — that is left
to the reviser, which is shown the full running history (see the orchestrator).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Higher weight = bigger hit to the quality score. BLOCKER is deliberately large so
# any blocker drags the score to the floor; it is also a hard gate in gate.py.
SEVERITY_WEIGHTS = {"BLOCKER": 100, "CONFUSING": 5, "NITPICK": 1}
MAX_QUALITY = 100

# A finding line starts (after optional bullet/quote markers) with an uppercase
# severity tag, optionally bracketed. Case-sensitive so prose like "no blockers"
# never registers as a finding.
_FINDING_LINE = re.compile(r"^[\s\-*>]*\[?(BLOCKER|CONFUSING|NITPICK)\]?\b")
_CELL_REF = re.compile(r"cells?\s+(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """One structured critic finding."""

    severity: str  # BLOCKER | CONFUSING | NITPICK
    cell: int | None
    text: str


@dataclass(frozen=True)
class LedgerEntry:
    """One notebook version and the issues attached to it."""

    label: str
    notebook: str
    report: str
    executed_ok: bool
    quality_score: int
    findings: tuple[Finding, ...]


class IssueLedger:
    """Running history of issues for the reviser.

    The ledger is intentionally simple: it accumulates each version's findings and
    renders them as a readable history so the reviser can see what has already been
    tried and what is still open.
    """

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def add(
        self,
        label: str,
        notebook: str,
        report: str,
        executed_ok: bool,
        quality_score: int,
        findings: tuple[Finding, ...],
    ) -> None:
        self._entries.append(
            LedgerEntry(
                label=label,
                notebook=notebook,
                report=report,
                executed_ok=executed_ok,
                quality_score=quality_score,
                findings=findings,
            )
        )

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def latest_quality_score(self) -> int | None:
        if not self._entries:
            return None
        return self._entries[-1].quality_score

    def render(self) -> str:
        if not self._entries:
            return "Issue ledger: (empty)"

        lines = ["Issue ledger", ""]
        for index, entry in enumerate(self._entries, start=1):
            execution = "clean" if entry.executed_ok else "failed"
            lines += [
                f"## Version {index}: {entry.label}",
                f"- notebook: `{entry.notebook}`",
                f"- report: `{entry.report}`",
                f"- execution: {execution}",
                f"- quality: {entry.quality_score}/100",
            ]
            if entry.findings:
                lines.append("- findings:")
                lines += [f"  - {finding.text}" for finding in entry.findings]
            else:
                lines.append("- findings: none")
            lines.append("")
        return "\n".join(lines).rstrip()


def parse_findings(feedback: str) -> tuple[Finding, ...]:
    """Extract findings from either a structured JSON block or free-text lines."""
    structured = _parse_structured_findings(feedback)
    if structured is not None:
        return structured

    findings: list[Finding] = []
    for line in feedback.splitlines():
        match = _FINDING_LINE.match(line)
        if not match:
            continue
        cell_match = _CELL_REF.search(line)
        findings.append(
            Finding(
                severity=match.group(1),
                cell=int(cell_match.group(1)) if cell_match else None,
                text=line.strip(),
            )
        )
    return tuple(findings)


def _parse_structured_findings(feedback: str) -> tuple[Finding, ...] | None:
    """Read the final JSON grading block emitted by the student prompt when present."""
    candidate = _extract_json_object(feedback)
    if candidate is None:
        return None

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    raw_findings = parsed.get("findings") if isinstance(parsed, dict) else None
    if not isinstance(raw_findings, list):
        return None

    findings: list[Finding] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "")).upper()
        if severity not in SEVERITY_WEIGHTS:
            continue
        raw_location = raw.get("location")
        location = raw_location if isinstance(raw_location, dict) else {}
        cell_index = location.get("cell_index")
        findings.append(
            Finding(
                severity=severity,
                cell=cell_index if isinstance(cell_index, int) else None,
                text=str(raw.get("text", "")).strip() or str(raw).strip(),
            )
        )
    return tuple(findings)


def _extract_json_object(feedback: str) -> str | None:
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", feedback, re.DOTALL)
    if fenced:
        return fenced[-1]

    stripped = feedback.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    return None


def burden(findings: tuple[Finding, ...]) -> int:
    """Severity-weighted sum of findings — the raw 'how much is wrong' number."""
    return sum(SEVERITY_WEIGHTS[finding.severity] for finding in findings)


def quality_score(findings: tuple[Finding, ...]) -> int:
    """A 0–100 teaching-quality score: 100 is flawless, 0 is floored by burden."""
    return max(0, min(MAX_QUALITY, MAX_QUALITY - burden(findings)))


def has_blocker(findings: tuple[Finding, ...]) -> bool:
    """Whether any finding is a BLOCKER — a crucial, must-not-ship issue."""
    return any(finding.severity == "BLOCKER" for finding in findings)
