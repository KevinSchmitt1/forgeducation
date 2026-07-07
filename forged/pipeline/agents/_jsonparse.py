"""Shared JSON extraction for the critic parsers (Student, Reviewer).

Structured outputs (`response_format={"type": "json_schema", ...}`, doc 15) return a **pure
JSON object** as the whole response, so the parser must try `json.loads(raw)` on the entire
string first. The earlier fence-first / brace-regex approach mis-parsed clean structured
JSON: the Student's limited-nesting brace regex matched a shallow *inner* object (e.g. the
`rubric`) instead of the whole report, so a valid grade was rejected with
"Grade report missing keys" and the paid run lost its quality judgment.

Fence/brace extraction is kept only as a fallback for non-structured providers (e.g. Ollama)
that wrap the JSON in prose or a ```json fence.
"""

from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _is_json_object(text: str) -> bool:
    try:
        return isinstance(json.loads(text), dict)
    except json.JSONDecodeError:
        return False


def extract_json_candidate(raw: str) -> str:
    """Return the best-effort JSON-object substring from an LLM response.

    Order (structured-output first, prose fallbacks after):
      1. the whole response, when it is already a JSON object (the structured-output case);
      2. the contents of a ```json ... ``` fence, when that parses as a JSON object;
      3. the first ``{`` to the last ``}`` (tolerates surrounding prose);
      4. the stripped response unchanged (lets the caller report a clean parse error).
    """
    text = raw.strip()
    if _is_json_object(text):
        return text

    fence = _FENCE.search(text)
    if fence and _is_json_object(fence.group(1).strip()):
        return fence.group(1).strip()

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]

    return text
