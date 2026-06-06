"""LLMAgent — runs one LLM-backed stage.

An agent is deliberately "sandboxed": it sees only its persona (system prompt) and
its declared input artifacts. It has no view of other agents' internal reasoning.
That isolation is what makes the stages behave like distinct collaborators rather
than one model talking to itself.
"""

from __future__ import annotations

from pathlib import Path

from .artifacts import Artifact, ArtifactStore
from .config import PipelineConfig, StageConfig
from .llm import LLMClient
from .notebook import build_notebook, cells_from_json, render_indexed


class LLMAgent:
    """Executes a single LLM stage: persona + inputs -> one output artifact."""

    def __init__(self, stage: StageConfig, pipeline: PipelineConfig, personas_dir: Path):
        self._stage = stage
        self._pipeline = pipeline
        self._personas_dir = personas_dir
        self._client = LLMClient(pipeline.resolved_model(stage))

    def run(self, store: ArtifactStore) -> Artifact:
        """Read inputs from the store, call the model, write the output artifact."""
        system_prompt = self._load_persona()
        user_prompt = self._build_user_prompt(store)

        raw = self._client.complete(system_prompt, user_prompt)
        content = self._post_process(raw)

        artifact = Artifact(
            name=self._stage.output,
            kind=self._stage.output_kind,
            content=content,
        )
        return store.put(artifact)

    def _load_persona(self) -> str:
        persona = self._stage.persona
        if persona is None:  # guaranteed by config validation for LLM stages; guard for type-safety
            raise ValueError(f"LLM stage '{self._stage.name}' is missing a persona file")
        persona_path = self._personas_dir / persona
        if not persona_path.is_file():
            raise FileNotFoundError(
                f"Persona file for stage '{self._stage.name}' not found: {persona_path}"
            )
        return persona_path.read_text(encoding="utf-8")

    def _build_user_prompt(self, store: ArtifactStore) -> str:
        """Present each input artifact in a clearly delimited block so the model
        can tell its sources apart."""
        sections = []
        for name in self._stage.inputs:
            artifact = store.get(name)
            # Notebooks are shown as an index-labelled listing so every agent
            # references cells by the same indices the executor reports.
            body = (
                render_indexed(artifact.content)
                if artifact.kind == "notebook"
                else artifact.content
            )
            sections.append(
                f"<artifact name=\"{name}\" kind=\"{artifact.kind}\">\n"
                f"{body}\n"
                f"</artifact>"
            )
        body = "\n\n".join(sections) if sections else "(no input artifacts)"
        return (
            f"You are operating as the '{self._stage.name}' stage of a lesson-"
            f"building pipeline. Your inputs follow.\n\n{body}\n\n"
            "Produce only your stage's output, following your role instructions."
        )

    def _post_process(self, raw: str) -> str:
        """Transform raw model text into the declared output kind. For notebooks,
        parse the JSON cell list and assemble a real .ipynb."""
        if self._stage.output_kind == "notebook":
            return build_notebook(cells_from_json(raw))
        return raw.strip()
