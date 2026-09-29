"""The remake decision — when a repair should become an informed rewrite.

C5 (doc 21) made *targeted repair* the default: a revision brief drives a patch, and
untouched cells stay untouched, which protects the good explanations an earlier round
produced. But repair is the wrong tool when the *shape* is wrong rather than the cells
— when repeated patches have not reduced the failures, or most of the notebook is
implicated anyway. Then the right move is to write it again — but *informed* by
everything the critics have said, or it is just another sample (docs/architecture/22 →
R7, D5).

This module makes that a **recorded decision**. The trigger is a judgement from
evidence the Reviser already has — how many repair rounds have run, and whether a
finding has persisted across them (the critique digest's recurrence, the C6 non-
convergence signal) — not a magic number. The thresholds below are named and
justified, but the part that is *deterministic and load-bearing* is that the decision
and its reason are always recorded, so a remake never happens silently. This mirrors
how routing records its reasons in the routing log.

Purely deterministic — no LLM, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass

from .digest import CritiqueDigest

# A remake is only ever considered once the author has actually been *given* repair
# rounds and they have not converged — one bad draft is not evidence the shape is
# wrong, it is evidence the first patch has not run yet. Two completed repair attempts
# is the point at which "patching isn't working" becomes a supportable claim rather
# than an early over-reaction.
REMAKE_MIN_REPAIR_ATTEMPTS = 2

# A finding that survived this many distinct iterations of patching is the non-
# convergence signal (C6): the loop is re-reporting the same root cause because
# targeted repair keeps missing it. Set to 3 because that is the corpus case — the
# PASSWORD validator bug recurred across iterations 1, 2 and 3 and was never fixed.
REMAKE_PERSISTENCE = 3


@dataclass(frozen=True)
class RemakeDecision:
    """Whether the next code-author pass should remake the lesson, and why.

    remake — True when the evidence says a rewrite will do better than another patch.
    reason — always populated, remake or not: this is the record that makes the
             decision non-silent, the way a RoutingDecision always carries a reason.
    """

    remake: bool
    reason: str


def decide_remake(
    repair_attempts: int,
    digest: CritiqueDigest,
    *,
    min_repair_attempts: int = REMAKE_MIN_REPAIR_ATTEMPTS,
    persistence: int = REMAKE_PERSISTENCE,
) -> RemakeDecision:
    """Decide whether the next code-author pass should remake rather than patch.

    Args:
        repair_attempts: how many code-author repair rounds have already run
            (state.get_stage_attempt_count(CODE_AUTHOR)). A remake is only weighed
            once repair has genuinely been tried and not converged.
        digest: the accumulated critique digest; its most persistent finding's
            recurrence is the non-convergence signal.
        min_repair_attempts / persistence: the judgement boundaries, exposed so tests
            and future calibration can move them without editing the logic.

    Returns:
        A RemakeDecision whose reason is always set — the recorded, non-silent
        outcome — mirroring how the router always records a routing reason.
    """
    max_recurrence = max((e.recurrence for e in digest.entries), default=0)

    if repair_attempts < min_repair_attempts:
        return RemakeDecision(
            remake=False,
            reason=(
                f"Repair by default: only {repair_attempts} repair round(s) so far "
                f"(a remake is not weighed until {min_repair_attempts}). Patch the "
                "cells the brief names."
            ),
        )

    if max_recurrence >= persistence:
        return RemakeDecision(
            remake=True,
            reason=(
                f"Remake: after {repair_attempts} repair rounds a finding has "
                f"persisted across {max_recurrence} iterations — targeted patching is "
                "not converging (C6). Rewrite the lesson informed by the accumulated "
                "critique below rather than patching the same root cause again."
            ),
        )

    return RemakeDecision(
        remake=False,
        reason=(
            f"Repair by default: {repair_attempts} repair round(s) run, but no finding "
            f"has persisted across {persistence}+ iterations — patching is still making "
            "progress. Patch the cells the brief names."
        ),
    )
