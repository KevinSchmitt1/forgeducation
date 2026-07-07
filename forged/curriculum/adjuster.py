"""PlanAdjuster — Tier-1 intent classifier for the front-door plan gate (doc 16, Phase 2).

The learner sees a proposed plan and types one sentence. This thin LLM wrapper turns that
sentence into a single structural `AdjustmentIntent` — the closed vocabulary the gate then
executes deterministically (merge/drop/force_single/reorder) or, for `confirm`/`cancel`,
acts on directly. Feedback that is not a structural edit degrades to `op="replan"`, the
safe non-destructive default that hands the sentence back to the full planner (Tier 2).

Mirrors `CurriculumPlanner`'s shape exactly: persona file + `LLMClient.complete`, injectable
`llm_client` for tests, no pipeline `Agent` base class. The context it sends the model is
**titles-only** (numbered module titles + the one sentence) — the structural guarantee
against interactive-loop token growth (doc 16, Design decision 5).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

# The closed operation vocabulary. Anything the model returns outside this set — or any
# parse failure — degrades to "replan", the same spirit as the student's graded=False.
_VALID_OPS = {
    "merge",
    "drop",
    "force_single",
    "reorder",
    "replan",
    "confirm",
    "cancel",
}

# Intent classification is a cheap reasoning task on ~100 tokens of context — same model
# family as the planner and critics.
DEFAULT_MODEL = "gpt-5-mini"

ADJUSTER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "plan_adjustment_intent",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": sorted(_VALID_OPS)},
                "targets": {"type": "array", "items": {"type": "integer"}},
                "instruction": {"type": "string"},
            },
            "required": ["op", "targets", "instruction"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class AdjustmentIntent:
    """One structural intent parsed from the learner's sentence.

    `targets` are the shown module numbers the op applies to (merge: exactly 2; drop: ≥1;
    reorder: a full permutation; otherwise empty). `instruction` is the learner's sentence
    verbatim — the Tier-2 replan path forwards it to the planner as guidance.
    """

    op: str
    targets: tuple[int, ...]
    instruction: str


class PlanAdjuster:
    """Classifies a learner sentence into a structural `AdjustmentIntent` via the LLM."""

    def __init__(
        self,
        personas_dir: Path | None = None,
        llm_client: Any = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.personas_dir: Path = Path("personas") if personas_dir is None else Path(personas_dir)
        self.persona: str = (self.personas_dir / "plan_adjuster.md").read_text(
            encoding="utf-8"
        )
        self.model: str = model
        if llm_client is not None:
            self._llm_client = llm_client
        else:  # pragma: no cover - exercised only in real runs, not unit tests
            from forged.config import ModelConfig
            from forged.llm import LLMClient

            self._llm_client = LLMClient(ModelConfig(model=model))

    def classify(self, module_titles: tuple[str, ...], sentence: str) -> AdjustmentIntent:
        """Classify `sentence` against the shown `module_titles` into an AdjustmentIntent.

        Never raises: an unparseable response or an unknown op degrades to
        `AdjustmentIntent(op="replan", …)` so the gate falls back to a guided re-plan
        rather than a guessed destructive edit.
        """
        user_msg = self._build_user_message(module_titles, sentence)
        try:
            raw = self._llm_client.complete(
                self.persona, user_msg, response_format=ADJUSTER_RESPONSE_FORMAT
            )
        except Exception as exc:  # noqa: BLE001 — classification degrades, never crashes
            _LOG.warning("PlanAdjuster LLM call failed, degrading to replan: %s", exc)
            return AdjustmentIntent(op="replan", targets=(), instruction=sentence)
        return self._parse_intent(raw, sentence)

    def _build_user_message(self, module_titles: tuple[str, ...], sentence: str) -> str:
        numbered = "\n".join(f"[{i}] {title}" for i, title in enumerate(module_titles))
        return f"Current plan (module titles):\n{numbered}\n\nLearner said:\n{sentence}"

    def _parse_intent(self, raw: str, sentence: str) -> AdjustmentIntent:
        data = _extract_json_object(raw)
        if not isinstance(data, dict):
            return AdjustmentIntent(op="replan", targets=(), instruction=sentence)

        op = data.get("op")
        if op not in _VALID_OPS:
            return AdjustmentIntent(op="replan", targets=(), instruction=sentence)

        targets = _int_tuple(data.get("targets"))
        # Trust the model's echo when present, but never lose the real sentence.
        instruction = str(data.get("instruction") or sentence).strip() or sentence
        return AdjustmentIntent(op=op, targets=targets, instruction=instruction)


# ── Helpers ────────────────────────────────────────────────────────────────────────


def _int_tuple(value: Any) -> tuple[int, ...]:
    """Coerce a JSON value into a tuple of ints; tolerate None/non-list/bad entries."""
    if not isinstance(value, list):
        return ()
    out: list[int] = []
    for item in value:
        if isinstance(item, bool):  # bool is a subclass of int — reject stray true/false
            continue
        if isinstance(item, int):
            out.append(item)
    return tuple(out)


def _extract_json_object(raw: str) -> Any | None:
    """Parse the first complete JSON object in the response.

    Tolerates a ```json fence or surrounding prose by slicing from the first '{' to the
    last '}'. Returns None when nothing parses, so the caller degrades to replan.
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
        _LOG.warning("PlanAdjuster: could not parse JSON from response")
        return None
