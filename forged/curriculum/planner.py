"""CurriculumPlanner — decompose a course brief into an ordered CourseSpec.

One level above the Lesson Planner: it decides whether a brief is one lesson or a short
ordered course, and emits the module specs. It loads `personas/curriculum_planner.md`,
calls the LLM with the brief + learner context, and parses the JSON response into a frozen
`CourseSpec`. Each module is an ordinary `TopicSpecification`, so a module run is a normal
agentic run (doc 13).

This does NOT subclass the pipeline `Agent` base class: it runs *above* the lesson loop and
has no `PipelineState`/`PipelineStage`. It is a thin LLM wrapper with a strict parser.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from forged.context import build_context_block
from forged.models import LearnerProfile, TopicSpecification

from .model import CourseSpec, ModuleSpec

_LOG = logging.getLogger(__name__)

_VALID_SCOPES = {"fundamentals", "implementation", "optimization", "usage"}
_VALID_DEPTHS = {"beginner", "intermediate", "advanced"}

# Curriculum planning is a reasoning task, not a code-generation one. Default to the
# same cheap reasoning model the lesson planner/critics use (gpt-5-mini) rather than the
# bare ModelConfig default — decompositions on gpt-4o-mini were noticeably coarser.
DEFAULT_MODEL = "gpt-5-mini"

_MODULE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scope": {"type": "string", "enum": sorted(_VALID_SCOPES)},
        "depth": {"type": "string", "enum": sorted(_VALID_DEPTHS)},
        "learning_objectives": {"type": "array", "items": {"type": "string"}},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "focus_areas": {"type": "array", "items": {"type": "string"}},
        "module_prerequisites": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title",
        "scope",
        "depth",
        "learning_objectives",
        "prerequisites",
        "focus_areas",
        "module_prerequisites",
    ],
    "additionalProperties": False,
}

# Strict JSON-schema response format (doc 15 parity, mirrors student.py). Used on OpenAI;
# the lenient `_extract_json_object` fallback stays for providers that ignore the parameter.
COURSE_PLAN_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "course_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "rationale": {"type": "string"},
                "modules": {"type": "array", "items": _MODULE_SCHEMA},
            },
            "required": ["title", "rationale", "modules"],
            "additionalProperties": False,
        },
    },
}


class CurriculumPlanner:
    """Turns a course brief + learner profile into a CourseSpec via the LLM."""

    def __init__(
        self,
        personas_dir: Path | None = None,
        llm_client: Any = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.personas_dir: Path = Path("personas") if personas_dir is None else Path(personas_dir)
        self.persona: str = (self.personas_dir / "curriculum_planner.md").read_text(
            encoding="utf-8"
        )
        self.model: str = model
        if llm_client is not None:
            self._llm_client = llm_client
        else:  # pragma: no cover - exercised only in real runs, not unit tests
            from forged.config import ModelConfig
            from forged.llm import LLMClient

            self._llm_client = LLMClient(ModelConfig(model=model))

    def plan(
        self,
        brief: str,
        learner_profile: LearnerProfile,
        topic_spec: TopicSpecification | None = None,
        guidance: str | None = None,
    ) -> CourseSpec:
        """Produce a CourseSpec for the brief, or raise ValueError on bad LLM output.

        `guidance`, when set, is the learner's verbatim adjustment request from the front-
        door gate (Tier-2 replan). It is appended as a must-honor block so the planner
        changes only what the learner asked and keeps the rest of the plan stable.
        """
        user_msg = self._build_user_message(brief, learner_profile, topic_spec, guidance)
        raw = self._llm_client.complete(
            self.persona, user_msg, response_format=COURSE_PLAN_RESPONSE_FORMAT
        )
        return self._parse_course(raw)

    def _build_user_message(
        self,
        brief: str,
        learner_profile: LearnerProfile,
        topic_spec: TopicSpecification | None,
        guidance: str | None = None,
    ) -> str:
        context = build_context_block(learner_profile, topic_spec)
        prefix = f"{context}\n\n" if context else ""
        suffix = (
            f"\n\nAdjustment request from the learner (must be honored): {guidance}"
            if guidance and guidance.strip()
            else ""
        )
        return f"{prefix}Course brief:\n{brief}{suffix}"

    # ── Parsing ──────────────────────────────────────────────────────────────────

    def _parse_course(self, raw: str) -> CourseSpec:
        data = _extract_json_object(raw)
        if data is None or not isinstance(data, dict):
            raise ValueError("curriculum planner did not return a JSON course object")

        modules_raw = data.get("modules")
        if not isinstance(modules_raw, list) or not modules_raw:
            raise ValueError("curriculum plan has no modules")

        modules = tuple(
            self._parse_module(m, order) for order, m in enumerate(modules_raw)
        )
        return CourseSpec(
            title=str(data.get("title", "")).strip() or "Untitled course",
            modules=modules,
            rationale=str(data.get("rationale", "")).strip(),
        )

    def _parse_module(self, module: Any, order: int) -> ModuleSpec:
        if not isinstance(module, dict):
            raise ValueError(f"curriculum module {order} is not an object")
        title = str(module.get("title", "")).strip()
        if not title:
            raise ValueError(f"curriculum module {order} has no title")

        scope = module.get("scope", "implementation")
        depth = module.get("depth", "intermediate")
        if scope not in _VALID_SCOPES:
            scope = "implementation"
        if depth not in _VALID_DEPTHS:
            depth = "intermediate"

        spec = TopicSpecification(
            title=title,
            scope=scope,
            learning_objectives=_str_list(module.get("learning_objectives")),
            prerequisites=_str_list(module.get("prerequisites")),
            constraints="",
            depth=depth,
            focus_areas=_str_list(module.get("focus_areas")),
        )
        return ModuleSpec(
            spec=spec,
            order=order,
            module_prerequisites=tuple(_str_list(module.get("module_prerequisites"))),
        )


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _str_list(value: Any) -> list[str]:
    """Coerce a JSON value into a list of non-blank strings; tolerate None/str/list."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _extract_json_object(raw: str) -> Any | None:
    """Parse the first complete JSON object in the response.

    Tolerates a ```json fence or surrounding prose by slicing from the first '{' to the
    last '}'. Returns None when nothing parses, so the caller can fail with a clear error.
    """
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        _LOG.warning("CurriculumPlanner: could not parse JSON from response")
        return None
