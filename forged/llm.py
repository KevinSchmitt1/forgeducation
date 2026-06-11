"""Pluggable LLM client.

Both OpenAI (cloud) and Ollama (local) speak the OpenAI chat-completions wire
format, so a single client covers both — only the base_url and key differ. This
is the privacy switch: point at Ollama and no lesson content leaves the machine.
"""

from __future__ import annotations

import os

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment, misc]

from .config import ModelConfig, Provider

# Default local Ollama endpoint (OpenAI-compatible). Overridable via env.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_PLACEHOLDER_KEY = "ollama"  # Ollama ignores the key but the SDK requires one.


class LLMClient:
    """Thin wrapper over the OpenAI SDK, configured per stage.

    One client instance corresponds to one resolved ModelConfig. The same code
    path serves cloud and local — `provider` only changes base_url and key.
    """

    def __init__(self, config: ModelConfig):
        self._config = config
        self._client = (
            OpenAI(**_connection_kwargs(config.provider))
            if OpenAI is not None
            else None
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Run a single system+user chat completion and return the text.

        Raises RuntimeError with context on any API failure so the orchestrator
        can report which stage broke and why.
        """
        if self._client is None:
            raise RuntimeError(
                "The openai package is not installed. Install it to run LLM-backed "
                "stages, or switch the pipeline to a local/non-LLM path."
            )
        messages: list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # OpenAI deprecated `max_tokens` in favour of `max_completion_tokens`
        # (required by o-series and newer models). Ollama's OpenAI-compatible
        # endpoint still expects `max_tokens`, so pick per provider.
        try:
            if self._config.provider is Provider.OLLAMA:
                response = self._client.chat.completions.create(
                    model=self._config.model,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    messages=messages,
                )
            else:
                response = self._client.chat.completions.create(
                    model=self._config.model,
                    temperature=self._config.temperature,
                    max_completion_tokens=self._config.max_tokens,
                    messages=messages,
                )
        except Exception as exc:  # noqa: BLE001 — re-raise with actionable context
            raise RuntimeError(
                f"LLM call failed (provider={self._config.provider.value}, "
                f"model={self._config.model}): {exc}"
            ) from exc

        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(
                f"LLM returned empty content (provider={self._config.provider.value}, "
                f"model={self._config.model})"
            )
        return content


def _connection_kwargs(provider: Provider) -> dict:
    """Resolve base_url + api_key for the chosen provider from the environment."""
    if provider is Provider.OLLAMA:
        base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        return {"base_url": base_url, "api_key": OLLAMA_PLACEHOLDER_KEY}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it or add it to .env, or switch the "
            "stage/pipeline provider to 'ollama' for local inference."
        )
    return {"api_key": api_key}
