"""Unit tests for the deterministic lesson-mode extractor.

No LLM, no network — these feed lesson-plan markdown to extract_lesson_mode() and
assert the returned LessonMode. The extractor is the shared contract every stage
builds against (docs/architecture/17-lesson-modes.md), so its fallbacks matter as
much as its happy path: anything absent/ambiguous must stay `executable`.

Run with:
    pytest tests/pipeline/test_mode.py -v
"""

from __future__ import annotations

import pytest

from forged.pipeline.mode import DEFAULT_MODE, extract_lesson_mode

# ── happy path: an explicit, recognized declaration wins ────────────────────────


@pytest.mark.parametrize("mode", ["executable", "artifact", "conceptual"])
def test_extracts_each_declared_mode(mode: str) -> None:
    # Arrange
    plan = f"# Lesson plan\n\n```lesson-mode\n{mode}\n```\n\n## Concept sequence\n"

    # Act
    result = extract_lesson_mode(plan)

    # Assert
    assert result == mode


def test_declaration_is_case_insensitive_on_tag_and_word() -> None:
    plan = "```Lesson-Mode\nARTIFACT\n```"
    assert extract_lesson_mode(plan) == "artifact"


def test_surrounding_blank_lines_are_tolerated() -> None:
    plan = "```lesson-mode\n\n   artifact   \n\n```"
    assert extract_lesson_mode(plan) == "artifact"


def test_first_block_wins_when_multiple_present() -> None:
    plan = "```lesson-mode\nconceptual\n```\nlater\n```lesson-mode\nexecutable\n```"
    assert extract_lesson_mode(plan) == "conceptual"


# ── conservative fallbacks: never silently drop rigor ───────────────────────────


def test_absent_block_falls_back_to_executable_default() -> None:
    plan = "# Lesson plan\n\n## Concept sequence\nno mode declared here"
    assert extract_lesson_mode(plan) == "executable"
    assert extract_lesson_mode(plan) == DEFAULT_MODE


def test_empty_plan_falls_back_to_default() -> None:
    assert extract_lesson_mode("") == DEFAULT_MODE


def test_unrecognized_word_falls_back_to_default_not_a_guess() -> None:
    # An unknown word must NOT be coerced toward artifact/conceptual — stay strict.
    plan = "```lesson-mode\nhands-on\n```"
    assert extract_lesson_mode(plan) == "executable"


def test_empty_block_body_falls_back_to_default() -> None:
    plan = "```lesson-mode\n\n```"
    assert extract_lesson_mode(plan) == DEFAULT_MODE


def test_requirements_block_is_not_mistaken_for_mode() -> None:
    # A different fenced block must not leak into mode detection.
    plan = "```requirements\ntransformers==4.44\n```\nno lesson-mode block"
    assert extract_lesson_mode(plan) == "executable"
