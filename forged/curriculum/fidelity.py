"""Course-level fidelity: does the decomposition still cover the whole topic?

The honesty invariant (doc 13): the union of the modules' capabilities must cover
every capability the original topic requested. The curriculum planner may *distribute*
capabilities across modules, but it may never *drop* one. This is the deterministic
backstop to the planner persona — the course-level analogue of R1's per-notebook
detector — and it reuses R1's exact distinctive-term coverage logic
(`forged.pipeline.fidelity.assess_capability_coverage`) so the two checks agree.

The haystack is the union of every module's capability text; the requested set is the
original topic's capabilities. A capability with no covering module surfaces in
`missing` — the signal that the decomposition silently dropped something.
"""

from __future__ import annotations

from collections.abc import Sequence

from forged.pipeline.fidelity import TopicFidelityReport, assess_capability_coverage

from .model import CourseSpec

# Term-coverage assumes a *capability statement* — a short, distinctive phrase like
# "train a LoRA adapter". A free-text brief ("Teach me how to work with AI agents: … and
# how the architecture of that should look.") is a paragraph: its distinctive-term set is
# large and full of connective words no module title will ever carry, so the check reports
# a drop no matter how faithful the decomposition is. Observed on 2026-07-28 and again on
# 2026-07-30 — both runs printed an identical, meaningless `⚠ DROPPED` for the whole topic.
# Real capabilities in the shipped templates run ~3–15 words; 30 leaves generous headroom.
MAX_ASSESSABLE_CAPABILITY_WORDS = 30


def assessable_capabilities(capabilities: Sequence[str]) -> tuple[str, ...]:
    """The subset of `capabilities` that term-coverage can honestly judge.

    Filters out paragraph-shaped entries (see `MAX_ASSESSABLE_CAPABILITY_WORDS`). An empty
    result means nothing discrete was requested — the caller must then report the check as
    *not assessed* rather than as passed or dropped.
    """
    return tuple(
        c for c in capabilities
        if c and c.strip() and len(c.split()) <= MAX_ASSESSABLE_CAPABILITY_WORDS
    )


def assess_course_fidelity(
    original_capabilities: Sequence[str], course: CourseSpec
) -> TopicFidelityReport:
    """Report which original capabilities the course's modules no longer cover.

    Args:
        original_capabilities: the capabilities the un-split topic requested
            (objectives + focus areas); blank entries are ignored.
        course: the proposed decomposition.

    Returns:
        A TopicFidelityReport over the original capabilities. `missing` non-empty ⇒ the
        decomposition dropped a requested capability — a failed honesty invariant.
    """
    haystack = "\n".join(course.all_capabilities)
    return assess_capability_coverage(haystack, list(original_capabilities))
