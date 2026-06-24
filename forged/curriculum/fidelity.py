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
