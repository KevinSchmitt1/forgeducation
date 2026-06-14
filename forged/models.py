"""Data models for structured inputs (learner profile, topic spec)."""

from __future__ import annotations

from dataclasses import dataclass
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
