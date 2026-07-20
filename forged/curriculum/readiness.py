"""ReadinessAssessor — pre-flight check on a single-module plan (doc 14, Part III).

The Curriculum Planner has already sized a topic down to one module; this checks whether
that single lesson is honestly reachable for THIS learner, or whether it would cram
foundational material in too shallowly (the same judgment `personas/planner.md` makes
mid-pipeline as a runtime backstop — this catches the same overflow BEFORE any paid
lesson-building spend).

Mirrors `CurriculumPlanner`/`PlanAdjuster`'s shape exactly: persona file + `LLMClient
.complete`, injectable `llm_client` for tests, no pipeline `Agent` base class. Fails OPEN on
any parse failure or LLM error (`reachable=True`) — the conservative default that never blocks
a build the assessor couldn't judge, mirroring `PlanAdjuster`'s degrade-to-safe-default stance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from forged.context import build_context_block
from forged.models import LearnerProfile, TopicSpecification

from .model import ReadinessVerdict

_LOG = logging.getLogger(__name__)

# A pre-flight judgment call, not code generation — same cheap reasoning model as the
# curriculum planner and lesson critics.
DEFAULT_MODEL = "gpt-5-mini"

READINESS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "readiness_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "reachable": {"type": "boolean"},
                "beachhead": {"type": "string"},
                "missing_foundations": {"type": "array", "items": {"type": "string"}},
                "unreachable_capabilities": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
            },
            "required": [
                "reachable",
                "beachhead",
                "missing_foundations",
                "unreachable_capabilities",
                "reason",
            ],
            "additionalProperties": False,
        },
    },
}

# Fail-open default: never invented if the assessor can't judge — proceed with the
# single-lesson build and rely on the in-pipeline planner + R1/Phase-4 as the runtime
# backstop, exactly as doc 14 Part III's "fail-open on parse failure" decision records.
_FAIL_OPEN_VERDICT = ReadinessVerdict(
    reachable=True,
    beachhead="",
    missing_foundations=(),
    unreachable_capabilities=(),
    reason="readiness assessor unavailable or unparseable — failing open to the single-lesson "
    "build",
)


class ReadinessAssessor:
    """Judges whether a single-module topic is honestly reachable for a learner."""

    def __init__(
        self,
        personas_dir: Path | None = None,
        llm_client: Any = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.personas_dir: Path = Path("personas") if personas_dir is None else Path(personas_dir)
        self.persona: str = (self.personas_dir / "readiness_assessor.md").read_text(
            encoding="utf-8"
        )
        self.model: str = model
        if llm_client is not None:
            self._llm_client = llm_client
        else:  # pragma: no cover - exercised only in real runs, not unit tests
            from forged.config import ModelConfig
            from forged.llm import LLMClient

            self._llm_client = LLMClient(ModelConfig(model=model))

    def assess(
        self,
        brief: str,
        learner_profile: LearnerProfile,
        topic_spec: TopicSpecification | None = None,
    ) -> ReadinessVerdict:
        """Return a ReadinessVerdict for `brief`; never raises — failures fail open."""
        user_msg = self._build_user_message(brief, learner_profile, topic_spec)
        try:
            raw = self._llm_client.complete(
                self.persona, user_msg, response_format=READINESS_RESPONSE_FORMAT
            )
        except Exception as exc:  # noqa: BLE001 — a failed check must never block a build
            _LOG.warning("ReadinessAssessor LLM call failed, failing open: %s", exc)
            return _FAIL_OPEN_VERDICT
        return self._parse_verdict(raw)

    def _build_user_message(
        self,
        brief: str,
        learner_profile: LearnerProfile,
        topic_spec: TopicSpecification | None,
    ) -> str:
        context = build_context_block(learner_profile, topic_spec)
        prefix = f"{context}\n\n" if context else ""
        return f"{prefix}Topic brief:\n{brief}"

    def _parse_verdict(self, raw: str) -> ReadinessVerdict:
        data = _extract_json_object(raw)
        if not isinstance(data, dict):
            return _FAIL_OPEN_VERDICT

        reachable = data.get("reachable")
        if not isinstance(reachable, bool):
            return _FAIL_OPEN_VERDICT

        return ReadinessVerdict(
            reachable=reachable,
            beachhead=str(data.get("beachhead", "")).strip(),
            missing_foundations=tuple(_str_list(data.get("missing_foundations"))),
            unreachable_capabilities=tuple(_str_list(data.get("unreachable_capabilities"))),
            reason=str(data.get("reason", "")).strip(),
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
    last '}'. Returns None when nothing parses, so the caller fails open.
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
        _LOG.warning("ReadinessAssessor: could not parse JSON from response")
        return None
