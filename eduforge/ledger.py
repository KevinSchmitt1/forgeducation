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


def parse_findings(feedback: str) -> tuple[Finding, ...]:
    """Extract findings from a critic's free-text feedback, in order."""
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


def burden(findings: tuple[Finding, ...]) -> int:
    """Severity-weighted sum of findings — the raw 'how much is wrong' number."""
    return sum(SEVERITY_WEIGHTS[finding.severity] for finding in findings)


def quality_score(findings: tuple[Finding, ...]) -> int:
    """A 0–100 teaching-quality score: 100 is flawless, 0 is floored by burden."""
    return max(0, min(MAX_QUALITY, MAX_QUALITY - burden(findings)))


def has_blocker(findings: tuple[Finding, ...]) -> bool:
    """Whether any finding is a BLOCKER — a crucial, must-not-ship issue."""
    return any(finding.severity == "BLOCKER" for finding in findings)
