"""A canned, offline stand-in for the planner-side LLM calls (`forged ui --fake-llm`).

Lets anyone click through the whole front door — author inputs, plan, edit, confirm,
launch — with no API key and no network, and is what the browser e2e drives. It answers
the three structured calls the UI makes (course plan, readiness verdict, plan-adjustment
intent) by their response-format name, deterministically. It never answers a lesson-
pipeline call: in fake mode the build is a dry run (`DryRunLauncher`), because a canned
plan must never reach a real, paid build.
"""

from __future__ import annotations

import json
import re
from typing import Any

_MODE_WORDS = ("executable", "artifact", "conceptual")
_SINGLE_WORDS = ("single", "one lesson", "one notebook", "don't split", "dont split")
_CONFIRM_WORDS = {"yes", "y", "ok", "okay", "go", "build", "build it", "looks good"}
_CANCEL_WORDS = {"no", "n", "cancel", "stop", "quit", "never mind"}

# (title suffix, lesson mode) for the canned three-module course — deliberately mixed
# modes, so the plan preview shows what a well-planned course looks like.
_COURSE_SHAPE = (
    ("foundations", "executable"),
    ("building it", "artifact"),
    ("design trade-offs", "conceptual"),
)


class FakeLLM:
    """Duck-types `LLMClient.complete` for the curriculum planner, readiness assessor
    and plan adjuster. Stateless; safe to share across sessions."""

    def complete(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
        response_format = kwargs.get("response_format") or {}
        name = response_format.get("json_schema", {}).get("name", "")
        if name == "course_plan":
            return json.dumps(_course_plan(user_prompt))
        if name == "readiness_verdict":
            return json.dumps(
                {
                    "reachable": True,
                    "beachhead": "",
                    "missing_foundations": [],
                    "unreachable_capabilities": [],
                    "reason": "offline demo: always reachable",
                }
            )
        if name == "plan_adjustment_intent":
            return json.dumps(_intent(user_prompt))
        raise RuntimeError(f"offline demo LLM has no canned answer for {name or 'this call'!r}")


def _course_plan(user_prompt: str) -> dict[str, Any]:
    brief = _after(user_prompt, "Course brief:\n").split("\n\nAdjustment request", 1)[0].strip()
    guidance = _after(user_prompt, "Adjustment request from the learner (must be honored):")
    capabilities = _bullets_under(user_prompt, "- Learning objectives:") + _bullets_under(
        user_prompt, "- Focus areas (priority order):"
    )
    capabilities = capabilities or [f"Understand {brief}"]
    shape = _COURSE_SHAPE[:1] if _mentions(guidance, _SINGLE_WORDS) else _COURSE_SHAPE
    modules: list[dict[str, Any]] = []
    for index, (suffix, mode) in enumerate(shape):
        # Round-robin the requested capabilities so the union covers every one of them.
        mine = capabilities[index :: len(shape)] or [f"Practise {brief}: {suffix}"]
        modules.append(
            {
                "title": brief if len(shape) == 1 else f"{brief}: {suffix}",
                "scope": "implementation",
                "depth": "intermediate",
                "learning_objectives": mine,
                "prerequisites": [],
                "focus_areas": [],
                "module_prerequisites": [modules[-1]["title"]] if modules else [],
                "lesson_mode": mode,
            }
        )
    rationale = (
        "Offline demo plan (no LLM was called)."
        + (f" Re-planned for: {guidance.strip()}" if guidance.strip() else "")
    )
    return {"title": f"{brief} (demo)", "rationale": rationale, "modules": modules}


def _intent(user_prompt: str) -> dict[str, Any]:
    sentence = _after(user_prompt, "Learner said:\n").strip()
    lowered = sentence.lower()
    numbers = [int(n) for n in re.findall(r"\d+", lowered)]
    module_count = len(re.findall(r"^\[\d+\] ", user_prompt, flags=re.MULTILINE))

    def intent(op: str, targets: list[int], instruction: str = sentence) -> dict[str, Any]:
        return {"op": op, "targets": targets, "instruction": instruction}

    if lowered.strip(" .!") in _CONFIRM_WORDS:
        return intent("confirm", [])
    if lowered.strip(" .!") in _CANCEL_WORDS:
        return intent("cancel", [])
    mode = next((m for m in _MODE_WORDS if m in lowered), None)
    if mode and len(numbers) == 1:
        return intent("set_mode", numbers, mode)
    if re.search(r"\b(merge|combine)\b", lowered) and len(numbers) == 2:
        return intent("merge", numbers)
    if re.search(r"\b(drop|remove|cut)\b", lowered) and numbers:
        return intent("drop", numbers)
    if re.search(r"\bswap\b", lowered) and len(numbers) == 2:
        order = list(range(module_count))
        a, b = numbers
        if a < module_count and b < module_count:
            order[a], order[b] = order[b], order[a]
        return intent("reorder", order)
    if _mentions(lowered, _SINGLE_WORDS):
        return intent("force_single", [])
    return intent("replan", [])


def _after(text: str, marker: str) -> str:
    return text.split(marker, 1)[1] if marker in text else ""


def _bullets_under(text: str, heading: str) -> list[str]:
    """The `  - item` bullets directly under a context-block heading (none → [])."""
    items: list[str] = []
    for line in _after(text, heading + "\n").splitlines():
        if not line.startswith("  - "):
            break
        item = line[4:].strip()
        if item and item != "(none)":
            items.append(item)
    return items


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)
