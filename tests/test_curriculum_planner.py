"""Tests for the CurriculumPlanner agent (doc 13, Phase 1d).

The planner loads `personas/curriculum_planner.md`, calls the LLM with the course brief +
learner context, and parses the JSON response into a frozen CourseSpec. Tests inject a stub
LLM client so they need no API key — the parse/contract behavior is what matters here.
"""

from __future__ import annotations

import json

import pytest

from forged.curriculum.model import CourseSpec
from forged.curriculum.planner import CurriculumPlanner
from forged.models import LearnerProfile


def _profile() -> LearnerProfile:
    return LearnerProfile(
        name="Kevin",
        description="Junior data scientist moving into AI engineering.",
        prior_knowledge=["Python", "SQL"],
        environment="jupyter_notebook",
        material_density="standard",
        learning_style="hands_on",
        background_context="Transitioning from data science to AI engineering.",
    )


class _StubClient:
    """Records the prompts it was called with and returns a canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None

    def complete(self, system_prompt, user_prompt, trace_context=None) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.response


_TWO_MODULE_JSON = json.dumps(
    {
        "title": "Setup and train local LLMs on M1",
        "rationale": "Setup and training each need real depth, so split them.",
        "modules": [
            {
                "title": "Set up the local stack",
                "scope": "implementation",
                "depth": "intermediate",
                "learning_objectives": ["install and verify a PyTorch + HF stack"],
                "focus_areas": ["device choice (mps vs cpu)"],
                "prerequisites": ["macOS on Apple Silicon"],
                "module_prerequisites": [],
            },
            {
                "title": "Fine-tune with LoRA",
                "scope": "implementation",
                "depth": "intermediate",
                "learning_objectives": ["fine-tune a small model with LoRA"],
                "focus_areas": ["LoRA adapters"],
                "prerequisites": [],
                "module_prerequisites": ["Set up the local stack"],
            },
        ],
    }
)


@pytest.mark.unit
def test_curriculum_planner_loads_persona() -> None:
    planner = CurriculumPlanner(llm_client=_StubClient("{}"))
    assert "Curriculum Planner" in planner.persona


@pytest.mark.unit
def test_curriculum_planner_defaults_to_gpt_5_mini() -> None:
    """Curriculum planning is a reasoning task — default to gpt-5-mini, not the bare
    ModelConfig gpt-4o-mini default (coarser decompositions)."""
    planner = CurriculumPlanner(llm_client=_StubClient("{}"))
    assert planner.model == "gpt-5-mini"


@pytest.mark.unit
def test_plan_parses_json_into_coursespec() -> None:
    planner = CurriculumPlanner(llm_client=_StubClient(_TWO_MODULE_JSON))

    course = planner.plan(brief="setup and train local LLMs on M1", learner_profile=_profile())

    assert isinstance(course, CourseSpec)
    assert course.title == "Setup and train local LLMs on M1"
    assert len(course.modules) == 2
    assert [m.order for m in course.modules] == [0, 1]
    assert course.modules[0].spec.title == "Set up the local stack"
    assert course.modules[1].module_prerequisites == ("Set up the local stack",)
    assert "fine-tune a small model with LoRA" in course.modules[1].capabilities


@pytest.mark.unit
def test_plan_accepts_fenced_json() -> None:
    """Robust to a ```json fence around the object."""
    fenced = f"```json\n{_TWO_MODULE_JSON}\n```"
    planner = CurriculumPlanner(llm_client=_StubClient(fenced))
    course = planner.plan(brief="x", learner_profile=_profile())
    assert len(course.modules) == 2


@pytest.mark.unit
def test_plan_single_module_course() -> None:
    one = json.dumps(
        {
            "title": "Intro to hashing",
            "rationale": "One focused lesson suffices.",
            "modules": [
                {
                    "title": "Intro to hashing",
                    "scope": "fundamentals",
                    "depth": "beginner",
                    "learning_objectives": ["explain what a hash function is"],
                    "focus_areas": [],
                    "prerequisites": [],
                    "module_prerequisites": [],
                }
            ],
        }
    )
    planner = CurriculumPlanner(llm_client=_StubClient(one))
    course = planner.plan(brief="intro to hashing", learner_profile=_profile())
    assert len(course.modules) == 1


@pytest.mark.unit
def test_plan_raises_on_unparseable_response() -> None:
    planner = CurriculumPlanner(llm_client=_StubClient("I could not produce a plan."))
    with pytest.raises(ValueError, match="curriculum"):
        planner.plan(brief="x", learner_profile=_profile())


@pytest.mark.unit
def test_plan_user_message_carries_brief_and_learner_context() -> None:
    stub = _StubClient(_TWO_MODULE_JSON)
    planner = CurriculumPlanner(llm_client=stub)
    planner.plan(brief="setup and train local LLMs on M1", learner_profile=_profile())
    assert stub.user_prompt is not None
    assert "setup and train local LLMs on M1" in stub.user_prompt
    assert "Kevin" in stub.user_prompt  # learner context block was included
