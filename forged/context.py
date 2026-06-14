"""Shared learner + topic context rendering for agent prompts.

Single source of truth used by BOTH pipelines — the linear `forged build` path
and the agentic `forged agentic` path — so neither can silently lose the
structured context the user supplied. Returns a plain-markdown block suitable
for prepending to any agent's user message.

Keeping this in one place is the whole point: before this module, the linear
path rendered context one way (fragile per-stage `.format` templates) and the
agentic path rendered none at all. One renderer means the two paths cannot drift.
"""

from __future__ import annotations

from .models import LearnerProfile, TopicSpecification

CONTEXT_HEADING = "## Lesson Context"


def build_context_block(
    learner_profile: LearnerProfile | None,
    topic_spec: TopicSpecification | None,
) -> str:
    """Render learner + topic context as a delimited markdown block.

    Each part is optional: a missing learner or topic is simply omitted. When
    neither is provided the result is an empty string, so callers can prepend it
    unconditionally without ever emitting a bare heading.
    """
    sections: list[str] = []
    if learner_profile is not None:
        sections.append(_render_learner(learner_profile))
    if topic_spec is not None:
        sections.append(_render_topic(topic_spec))
    if not sections:
        return ""
    return f"{CONTEXT_HEADING}\n\n" + "\n\n".join(sections)


def _bullets(items: list[str]) -> str:
    """Indented markdown bullets, or an explicit '(none)' so an empty list is
    never silently invisible to the model."""
    return "\n".join(f"  - {item}" for item in items) if items else "  - (none)"


def _render_learner(profile: LearnerProfile) -> str:
    return "\n".join(
        [
            f"### Target learner — {profile.name}",
            profile.description.strip(),
            "",
            "- Prior knowledge:",
            _bullets(profile.prior_knowledge),
            f"- Environment: {profile.environment}",
            f"- Material density: {profile.material_density}",
            f"- Learning style: {profile.learning_style}",
            f"- Background: {profile.background_context.strip()}",
        ]
    )


def _render_topic(topic: TopicSpecification) -> str:
    return "\n".join(
        [
            f"### Topic — {topic.title}",
            f"- Scope: {topic.scope}",
            f"- Depth: {topic.depth}",
            "- Learning objectives:",
            _bullets(topic.learning_objectives),
            "- Prerequisites:",
            _bullets(topic.prerequisites),
            "- Focus areas (priority order):",
            _bullets(topic.focus_areas),
            f"- Constraints: {topic.constraints.strip()}",
        ]
    )
