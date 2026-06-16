"""Pipeline configuration: typed, validated, loaded from YAML.

The YAML file is the single source of truth for *which* agents run, in *what*
order, reading and writing *which* artifacts. This is the "dynamic pipeline" knob:
edit the YAML to add/remove/reorder stages without touching Python.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class Provider(str, Enum):
    """Which LLM backend a stage talks to. Both speak the OpenAI wire format."""

    OPENAI = "openai"
    OLLAMA = "ollama"


class StageType(str, Enum):
    """LLM stages call a model; non-LLM stages run deterministic code."""

    LLM = "llm"
    EXECUTOR = "executor"


class ModelConfig(BaseModel):
    """Resolved model settings for a single LLM call."""

    provider: Provider = Provider.OPENAI
    model: str = "gpt-4o-mini"
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)


class StageConfig(BaseModel):
    """One step in the pipeline — a single agent with a clear input/output contract."""

    name: str
    type: StageType = StageType.LLM
    # Persona file (relative to the personas dir) holding this agent's system prompt.
    persona: str | None = None
    # Artifact names this stage reads. Each must be produced by an earlier stage
    # (or be the seed artifact).
    inputs: list[str] = Field(default_factory=list)
    # Artifact name this stage writes. Downstream stages reference it by this name.
    output: str
    # Content type of the output artifact: "text" (markdown), "notebook" (.ipynb
    # assembled from the model's JSON cells), or "json". Decides post-processing.
    output_kind: str = "text"
    # Per-stage model override; falls back to pipeline defaults when omitted.
    model: ModelConfig | None = None
    # Free-form knobs for non-LLM stages (e.g. executor timeout).
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_persona_for_llm(self) -> StageConfig:
        if self.type is StageType.LLM and not self.persona:
            raise ValueError(f"LLM stage '{self.name}' must declare a persona file")
        return self


class RevisionPolicy(BaseModel):
    """How the bounded revision loop should behave."""

    max_iterations: int = Field(default=3, ge=1)
    min_quality_score: int = Field(default=90, ge=0, le=100)
    require_progress: bool = True
    reviser: str
    critics: list[str] = Field(min_length=1)
    executor_params: dict = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    """The whole pipeline: ordered stages plus shared defaults."""

    name: str
    defaults: ModelConfig = Field(default_factory=ModelConfig)
    stage_models: dict[str, ModelConfig] = Field(default_factory=dict)
    stages: list[StageConfig]
    revision: RevisionPolicy | None = None

    @model_validator(mode="after")
    def _check_dataflow(self) -> PipelineConfig:
        """Fail fast if a stage reads an artifact nothing has produced yet, or if
        two stages write the same artifact name."""
        if not self.stages:
            raise ValueError("Pipeline must declare at least one stage")

        produced: set[str] = set(SEED_ARTIFACTS)
        seen_names: set[str] = set()
        for stage in self.stages:
            if stage.name in seen_names:
                raise ValueError(f"Duplicate stage name: '{stage.name}'")
            seen_names.add(stage.name)

            missing = [inp for inp in stage.inputs if inp not in produced]
            if missing:
                raise ValueError(
                    f"Stage '{stage.name}' reads artifact(s) {missing} that no "
                    f"earlier stage produces. Available: {sorted(produced)}"
                )
            if stage.output in produced:
                raise ValueError(
                    f"Stage '{stage.name}' overwrites artifact '{stage.output}' "
                    "already produced upstream — use a distinct name"
                )
            produced.add(stage.output)

        if self.revision is not None:
            has_executor = any(stage.type is StageType.EXECUTOR for stage in self.stages)
            has_notebook = any(stage.output_kind == "notebook" for stage in self.stages)
            if not has_executor or not has_notebook:
                raise ValueError(
                    "Revision policy requires at least one executor and one notebook "
                    "output in the linear pipeline"
                )
        return self

    def resolved_model(self, stage: StageConfig) -> ModelConfig:
        """Resolve the model for a concrete stage config.

        Precedence:
          1. Explicit stage.model override
          2. stage_models[stage.name]
          3. pipeline defaults
        """
        return stage.model or self.stage_models.get(stage.name) or self.defaults

    def resolved_model_name(self, stage_name: str) -> ModelConfig:
        """Resolve the model for a logical stage name.

        Used for synthesized stages that do not exist as base pipeline stages,
        such as the linear revision-loop reviser, and for the agentic graph's
        logical agents.
        """
        stage = next((item for item in self.stages if item.name == stage_name), None)
        if stage is not None and stage.model is not None:
            return stage.model
        return self.stage_models.get(stage_name) or self.defaults


# Seed artifacts every pipeline starts from, before any stage runs:
#   brief   — the user's lesson topic/request
#   profile — the target learner's prior knowledge + environment/prerequisites
# Stages may list either as an input.
SEED_ARTIFACTS = ("brief", "profile")


def load_pipeline(path: str | Path) -> PipelineConfig:
    """Read and validate a pipeline YAML file. Raises on any structural error."""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Pipeline config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Pipeline config must be a YAML mapping, got {type(raw).__name__}")

    return PipelineConfig.model_validate(raw)
