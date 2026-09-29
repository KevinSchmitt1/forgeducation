"""Unit tests for the critique digest (docs/architecture/22 → R6)."""

from __future__ import annotations

import pytest

from forged.pipeline.digest import (
    CritiqueDigest,
    build_digest,
    render_digest,
)
from forged.pipeline.state import (
    Evidence,
    IterationFindings,
    Location,
    LocationType,
    Scope,
    Severity,
)


def _finding(text: str, *, severity: Severity = "MEDIUM", scope: Scope = "content",
             source: str = "student") -> Evidence:
    return Evidence(
        source=source,
        severity=severity,
        scope=scope,
        location=Location(type=LocationType.GLOBAL),
        text=text,
    )


def _history(*iterations: tuple[int, list[Evidence]]) -> list[IterationFindings]:
    return [IterationFindings(iteration=i, findings=tuple(fs)) for i, fs in iterations]


@pytest.mark.unit
def test_empty_history_yields_empty_digest() -> None:
    assert build_digest([]).is_empty
    assert build_digest(_history((0, []))).is_empty


@pytest.mark.unit
def test_blank_text_findings_are_ignored() -> None:
    digest = build_digest(_history((0, [_finding("   ")])))
    assert digest.is_empty


@pytest.mark.unit
def test_restated_finding_across_iterations_collapses_to_one_entry() -> None:
    """The same issue restated in different words, at different cells, is one entry."""
    hist = _history(
        (1, [_finding(
            "The forbidden-pattern validator uses a case-sensitive PASSWORD regex "
            "which misses lowercase password occurrences."
        )]),
        (2, [_finding(
            "The validator forbidden-pattern PASSWORD regex is case-sensitive and "
            "misses lowercase password occurrences."
        )]),
    )
    digest = build_digest(hist)
    assert len(digest.entries) == 1
    entry = digest.entries[0]
    assert entry.recurrence == 2
    assert entry.iterations == (1, 2)
    assert entry.occurrences == 2


@pytest.mark.unit
def test_distinct_issues_stay_separate() -> None:
    hist = _history((0, [
        _finding("Cell 4 raises an IndentationError before the function definition.",
                 severity="BLOCKER", scope="code"),
        _finding("The forbidden PASSWORD regex is case-sensitive and misses lowercase.",
                 scope="content"),
    ]))
    digest = build_digest(hist)
    assert len(digest.entries) == 2


@pytest.mark.unit
def test_persistent_low_severity_outranks_one_off_high_severity() -> None:
    """Consequence, not severity alone: a recurring nitpick beats a one-off blocker.

    This is the D3 defect the digest exists to fix — a root cause filed LOW and
    buried under blockers that were each transient.
    """
    persistent = (
        "The forbidden PASSWORD regex is case-sensitive by design and misses "
        "lowercase password occurrences in the validator."
    )
    hist = _history(
        (0, [_finding("Cell 4 raises an IndentationError, halting execution.",
                      severity="BLOCKER", scope="code")]),
        (1, [_finding(persistent, severity="LOW", scope="content")]),
        (2, [_finding(persistent, severity="LOW", scope="content")]),
    )
    digest = build_digest(hist)
    top = digest.entries[0]
    assert "PASSWORD" in top.text
    assert top.recurrence == 2
    assert top.severity == "LOW"


@pytest.mark.unit
def test_entry_severity_is_the_worst_in_the_cluster() -> None:
    text = (
        "The forbidden PASSWORD regex is case-sensitive and misses lowercase "
        "password occurrences across the validator patterns."
    )
    hist = _history(
        (1, [_finding(text, severity="LOW")]),
        (2, [_finding(text, severity="HIGH")]),
    )
    digest = build_digest(hist)
    assert len(digest.entries) == 1
    assert digest.entries[0].severity == "HIGH"


@pytest.mark.unit
def test_sources_are_aggregated_and_sorted() -> None:
    text = (
        "The forbidden PASSWORD regex is case-sensitive and misses lowercase "
        "password occurrences across the validator patterns."
    )
    hist = _history(
        (1, [_finding(text, source="student")]),
        (1, [_finding(text, source="reviewer")]),
    )
    digest = build_digest(hist)
    assert digest.entries[0].sources == ("reviewer", "student")
    # Same iteration raised by both critics ⇒ recurrence is still 1 (one iteration).
    assert digest.entries[0].recurrence == 1
    assert digest.entries[0].occurrences == 2


@pytest.mark.unit
def test_clustering_never_crosses_scope() -> None:
    """Findings that share words but sit in different scopes are not merged."""
    shared = "the validator regex pattern checks the forbidden password string"
    hist = _history((0, [
        _finding(shared, scope="code"),
        _finding(shared, scope="content"),
    ]))
    digest = build_digest(hist)
    assert len(digest.entries) == 2


@pytest.mark.unit
def test_build_digest_is_deterministic() -> None:
    hist = _history(
        (0, [_finding("Cell 4 raises an IndentationError.", severity="BLOCKER", scope="code")]),
        (1, [_finding("The PASSWORD regex is case-sensitive and misses lowercase leaks.")]),
    )
    assert build_digest(hist) == build_digest(hist)


@pytest.mark.unit
def test_render_empty_digest_is_empty_string() -> None:
    assert render_digest(CritiqueDigest()) == ""


@pytest.mark.unit
def test_render_marks_recurring_findings_with_iteration_span() -> None:
    persistent = (
        "The forbidden PASSWORD regex is case-sensitive and misses lowercase "
        "password occurrences across the validator patterns."
    )
    hist = _history(
        (1, [_finding(persistent)]),
        (2, [_finding(persistent)]),
        (3, [_finding(persistent)]),
    )
    rendered = render_digest(build_digest(hist))
    assert "Accumulated critique" in rendered
    assert "seen in iters 1, 2, 3" in rendered


@pytest.mark.unit
def test_render_limit_omits_tail_and_notes_the_count() -> None:
    texts = [
        "The indentation before the helper function definition breaks execution.",
        "The markdown checklist renders literal backslash-n escape sequences.",
        "The subprocess validator exits nonzero without printing a JSON marker.",
        "The heading detection compares titles with a brittle startswith call.",
        "The commit step assumes a git identity that the sandbox never configured.",
        "The AWS access-key heuristic regex triggers false positives on samples.",
    ]
    hist = _history((0, [_finding(t, scope="code") for t in texts]))
    digest = build_digest(hist)
    assert len(digest.entries) == len(texts)
    rendered = render_digest(digest, limit=2)
    assert "\n1. " in rendered and "\n2. " in rendered
    assert "\n3. " not in rendered
    assert "omitted" in rendered
