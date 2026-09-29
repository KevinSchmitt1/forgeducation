"""Unit tests for the remake decision (docs/architecture/22 → R7)."""

from __future__ import annotations

import pytest

from forged.pipeline.digest import CritiqueDigest, DigestEntry
from forged.pipeline.remake import (
    REMAKE_MIN_REPAIR_ATTEMPTS,
    REMAKE_PERSISTENCE,
    decide_remake,
)


def _digest_with_recurrence(recurrence: int) -> CritiqueDigest:
    """A digest whose most persistent finding recurs across `recurrence` iterations."""
    if recurrence <= 0:
        return CritiqueDigest()
    entry = DigestEntry(
        text="A persistent root cause the patches keep missing.",
        severity="LOW",
        scope="content",
        sources=("reviewer",),
        iterations=tuple(range(1, recurrence + 1)),
        occurrences=recurrence,
    )
    return CritiqueDigest(entries=(entry,))


@pytest.mark.unit
def test_no_remake_before_min_repair_attempts_even_when_persistent() -> None:
    """One bad draft is not evidence the shape is wrong — repair must be tried first."""
    decision = decide_remake(
        repair_attempts=REMAKE_MIN_REPAIR_ATTEMPTS - 1,
        digest=_digest_with_recurrence(REMAKE_PERSISTENCE + 2),
    )
    assert decision.remake is False
    assert decision.reason  # always recorded


@pytest.mark.unit
def test_no_remake_when_patching_is_still_converging() -> None:
    """Enough repair rounds, but no finding has persisted — keep patching."""
    decision = decide_remake(
        repair_attempts=REMAKE_MIN_REPAIR_ATTEMPTS,
        digest=_digest_with_recurrence(REMAKE_PERSISTENCE - 1),
    )
    assert decision.remake is False
    assert decision.reason


@pytest.mark.unit
def test_remake_fires_on_non_convergence() -> None:
    """Repair tried, and a finding survived every round → remake, informed by it."""
    decision = decide_remake(
        repair_attempts=REMAKE_MIN_REPAIR_ATTEMPTS,
        digest=_digest_with_recurrence(REMAKE_PERSISTENCE),
    )
    assert decision.remake is True
    assert "persisted" in decision.reason.lower()


@pytest.mark.unit
def test_decision_reason_is_always_populated() -> None:
    """A remake never happens silently — nor does a decision not to remake."""
    for attempts in range(0, REMAKE_MIN_REPAIR_ATTEMPTS + 2):
        for recurrence in range(0, REMAKE_PERSISTENCE + 2):
            decision = decide_remake(
                repair_attempts=attempts,
                digest=_digest_with_recurrence(recurrence),
            )
            assert decision.reason.strip()


@pytest.mark.unit
def test_empty_digest_never_remakes() -> None:
    decision = decide_remake(
        repair_attempts=REMAKE_MIN_REPAIR_ATTEMPTS + 5,
        digest=CritiqueDigest(),
    )
    assert decision.remake is False
