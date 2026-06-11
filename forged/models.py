"""Data models for structured inputs (learner profile, topic spec, assessment)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


@dataclass
class LearnerProfile:
    """Describes the learner and how content should be shaped."""

    name: str
    description: str
    prior_knowledge: list[str]
    environment: Literal[
        "jupyter_notebook",
        "google_colab",
        "vscode",
        "ide",
        "cli",
        "book",
    ]
    material_density: Literal["dense", "standard", "rich"]
    learning_style: Literal[
        "socratic",
        "project_based",
        "visual",
        "hands_on",
        "reference",
    ]
    background_context: str

    @classmethod
    def from_yaml(cls, path: str | Path) -> LearnerProfile:
        """Load from YAML file."""
        try:
            import yaml
        except ImportError:
            raise ImportError("pyyaml required; install with: pip install pyyaml") from None

        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_prompt_context(self) -> dict:
        """Format for use in LLM prompts."""
        return {
            "name": self.name,
            "prior_knowledge": "\n  - ".join(self.prior_knowledge),
            "environment": self.environment,
            "material_density": self.material_density,
            "learning_style": self.learning_style,
            "background_context": self.background_context,
        }


@dataclass
class TopicSpecification:
    """Defines what should be learned."""

    title: str
    scope: Literal["fundamentals", "implementation", "optimization", "usage"]
    learning_objectives: list[str]
    prerequisites: list[str]
    constraints: str
    depth: Literal["beginner", "intermediate", "advanced"]
    focus_areas: list[str]

    @classmethod
    def from_yaml(cls, path: str | Path) -> TopicSpecification:
        """Load from YAML file."""
        try:
            import yaml
        except ImportError:
            raise ImportError("pyyaml required; install with: pip install pyyaml") from None

        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_prompt_context(self) -> dict:
        """Format for use in LLM prompts."""
        return {
            "title": self.title,
            "scope": self.scope,
            "learning_objectives": "\n  - ".join(self.learning_objectives),
            "prerequisites": "\n  - ".join(self.prerequisites),
            "constraints": self.constraints,
            "depth": self.depth,
            "focus_areas": "\n  - ".join(self.focus_areas),
        }


@dataclass
class ProjectAssessment:
    """Project-based assessment specification."""

    description: str
    starter_context: str
    difficulty: Literal["beginner", "intermediate", "advanced"]
    time_estimate: str


@dataclass
class KnowledgeTest:
    """Knowledge test specification."""

    format: Literal[
        "multiple_choice",
        "fill_in_code",
        "conceptual_questions",
        "exercises",
    ]
    count: int
    difficulty: Literal["beginner", "intermediate", "advanced"]


@dataclass
class AssessmentApproach:
    """How learning should be validated."""

    type: Literal["project", "knowledge_test", "both"]
    project: ProjectAssessment | None = None
    knowledge_test: KnowledgeTest | None = None
    assessment_difficulty: Literal[
        "matches_topic",
        "slightly_harder",
        "significantly_harder",
    ] = "matches_topic"

    @classmethod
    def from_yaml(cls, path: str | Path) -> AssessmentApproach:
        """Load from YAML file."""
        try:
            import yaml
        except ImportError:
            raise ImportError("pyyaml required; install with: pip install pyyaml") from None

        with open(path) as f:
            data = yaml.safe_load(f)

        # Handle nested objects
        if "project" in data and data["project"]:
            data["project"] = ProjectAssessment(**data["project"])
        if "knowledge_test" in data and data["knowledge_test"]:
            data["knowledge_test"] = KnowledgeTest(**data["knowledge_test"])

        return cls(**data)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)
