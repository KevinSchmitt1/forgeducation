"""Pluggable LLM client.

Both OpenAI (cloud) and Ollama (local) speak the OpenAI chat-completions wire
format, so a single client covers both — only the base_url and key differ. This
is the privacy switch: point at Ollama and no lesson content leaves the machine.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from langfuse.types import TraceContext
    from openai._types import Omit as _OmitType

try:
    from openai import OpenAI
    from openai._types import Omit as _OmitSentinel
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment, misc]
    _OmitSentinel = None  # type: ignore[assignment, misc]

try:
    from langfuse import Langfuse
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    Langfuse = None  # type: ignore[assignment, misc]

from .config import ModelConfig, Provider
from .usage import UsageRecord, record_usage

# Default local Ollama endpoint (OpenAI-compatible). Overridable via env.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_PLACEHOLDER_KEY = "ollama"  # Ollama ignores the key but the SDK requires one.
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMTraceContext:
    """Metadata used to group one LLM call into a Langfuse trace.

    One pipeline run should reuse the same ``run_id`` across all stages so the
    resulting generations land under a stable trace id.
    """

    stage_name: str
    pipeline_kind: str
    run_id: str
    run_dir: str | None = None
    pipeline_name: str | None = None
    iteration: int | None = None
    input_artifacts: tuple[str, ...] = ()
    output_artifact: str | None = None


class _LangfuseTracer:
    """Lazy Langfuse integration for per-call generation tracing.

    The tracer is intentionally optional: tests and local runs without
    LANGFUSE_* credentials should keep working with zero behavior change.
    """

    def __init__(self) -> None:
        self._client: Langfuse | None = None
        self._disabled = False
        self._lock = threading.Lock()
        self._registered_atexit = False

    def start_generation(
        self,
        config: ModelConfig,
        messages: list[dict[str, str]],
        trace_context: LLMTraceContext | None,
    ) -> Any | None:
        client = self._ensure_client()
        if client is None:
            return None

        metadata = self._metadata(config, trace_context)
        observation_name = (
            f"{trace_context.pipeline_kind}.{trace_context.stage_name}"
            if trace_context is not None
            else "llm.complete"
        )
        model_parameters: dict[str, str | int | float | bool | list[str] | None] = {
            "max_tokens": config.max_tokens,
        }
        if config.temperature is not None:
            model_parameters["temperature"] = config.temperature
        return client.start_observation(
            name=observation_name,
            as_type="generation",
            trace_context=self._trace_payload(client, trace_context),
            input=messages,
            metadata=metadata,
            model=config.model,
            model_parameters=model_parameters,
        )

    def record_success(
        self,
        observation: Any | None,
        output: str,
        usage_details: dict[str, int] | None,
    ) -> None:
        if observation is None:
            return
        try:
            observation.update(output=output, usage_details=usage_details)
            observation.end()
        except Exception as exc:  # noqa: BLE001 - observability must not break LLM calls
            _LOG.warning("Langfuse success recording failed: %s", exc)

    def record_error(self, observation: Any | None, message: str) -> None:
        if observation is None:
            return
        try:
            observation.update(level="ERROR", status_message=message)
            observation.end()
        except Exception as exc:  # noqa: BLE001 - observability must not break LLM calls
            _LOG.warning("Langfuse error recording failed: %s", exc)

    def _ensure_client(self) -> Langfuse | None:
        if self._disabled:
            return None
        if self._client is not None:
            return self._client

        if Langfuse is None or not _langfuse_configured():
            _LOG.debug("Langfuse tracing disabled: SDK unavailable or credentials missing")
            self._disabled = True
            return None

        with self._lock:
            if self._disabled:
                return None
            if self._client is not None:
                return self._client

            kwargs: dict[str, Any] = {
                "public_key": os.getenv("LANGFUSE_PUBLIC_KEY"),
                "secret_key": os.getenv("LANGFUSE_SECRET_KEY"),
            }
            if host := os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL"):
                kwargs["host"] = host
            if environment := os.getenv("LANGFUSE_ENV"):
                kwargs["environment"] = environment
            if release := os.getenv("LANGFUSE_RELEASE"):
                kwargs["release"] = release

            try:
                self._client = Langfuse(**kwargs)
            except Exception as exc:  # noqa: BLE001 - tracing is best-effort
                _LOG.warning("Langfuse init failed, tracing disabled: %s", exc)
                self._disabled = True
                return None

            if not self._registered_atexit:
                atexit.register(self._shutdown)
                self._registered_atexit = True
        return self._client

    def _shutdown(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
            self._client.shutdown()
        except Exception:  # noqa: BLE001 - best-effort shutdown only
            pass

    def _trace_payload(
        self,
        client: Langfuse,
        trace_context: LLMTraceContext | None,
    ) -> TraceContext | None:
        if trace_context is None:
            return None
        seed = f"{trace_context.pipeline_kind}:{trace_context.run_id}"
        return cast("TraceContext", {"trace_id": client.create_trace_id(seed=seed)})

    def _metadata(
        self,
        config: ModelConfig,
        trace_context: LLMTraceContext | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": config.provider.value,
            "model": config.model,
        }
        if trace_context is None:
            return metadata

        metadata.update(
            {
                "stage_name": trace_context.stage_name,
                "pipeline_kind": trace_context.pipeline_kind,
                "run_id": trace_context.run_id,
                "run_dir": trace_context.run_dir,
                "pipeline_name": trace_context.pipeline_name,
                "iteration": trace_context.iteration,
                "input_artifacts": list(trace_context.input_artifacts),
                "output_artifact": trace_context.output_artifact,
            }
        )
        return metadata


_TRACER = _LangfuseTracer()


class LLMClient:
    """Thin wrapper over the OpenAI SDK, configured per stage.

    One client instance corresponds to one resolved ModelConfig. The same code
    path serves cloud and local — `provider` only changes base_url and key.
    """

    def __init__(self, config: ModelConfig):
        self._config = config
        self._client: OpenAI | None = None
        self._tracer = _TRACER

    def _ensure_client(self) -> OpenAI:
        """Build the SDK client on first use.

        Lazy on purpose: constructing agents (and therefore LLMClient) must not
        require credentials — the offline test suite builds real agents with no
        API key. The key is resolved only when a completion is actually requested,
        and a missing key still fails with the same actionable message.
        """
        if self._client is not None:
            return self._client
        if OpenAI is None:
            raise RuntimeError(
                "The openai package is not installed. Install it to run LLM-backed "
                "stages, or switch the pipeline to a local/non-LLM path."
            )
        self._client = OpenAI(**_connection_kwargs(self._config.provider))
        return self._client

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        trace_context: LLMTraceContext | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Run a single system+user chat completion and return the text.

        Raises RuntimeError with context on any API failure so the orchestrator
        can report which stage broke and why.
        """
        client = self._ensure_client()
        messages: list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        observation = self._tracer.start_generation(self._config, messages, trace_context)
        # OpenAI deprecated `max_tokens` in favour of `max_completion_tokens`
        # (required by o-series and newer models). Ollama's OpenAI-compatible
        # endpoint still expects `max_tokens`, so pick per provider.
        # _OmitSentinel tells the OpenAI SDK to omit the parameter entirely — required
        # for models like gpt-5/gpt-5-mini that reject any non-default temperature.
        temperature: float | _OmitType | None = (
            self._config.temperature if self._config.temperature is not None else None
        )
        if temperature is None and _OmitSentinel is not None:
            temperature = _OmitSentinel()
        try:
            if self._config.provider is Provider.OLLAMA:
                response = client.chat.completions.create(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    messages=messages,
                    temperature=temperature,
                )
            else:
                kwargs: dict[str, Any] = {
                    "model": self._config.model,
                    "max_completion_tokens": self._config.max_tokens,
                    "messages": messages,
                    "temperature": temperature,
                }
                if response_format is not None:
                    kwargs["response_format"] = response_format
                response = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — re-raise with actionable context
            self._tracer.record_error(observation, str(exc))
            raise RuntimeError(
                f"LLM call failed (provider={self._config.provider.value}, "
                f"model={self._config.model}): {exc}"
            ) from exc

        choice = response.choices[0]
        content = choice.message.content
        if not content:
            refusal = getattr(choice.message, "refusal", None)
            finish = getattr(choice, "finish_reason", None)
            detail = f"refusal={refusal!r}" if refusal else f"finish_reason={finish!r}"
            _LOG.error(
                "LLM returned empty content — %s (provider=%s, model=%s)",
                detail,
                self._config.provider.value,
                self._config.model,
            )
            self._tracer.record_error(observation, f"empty content: {detail}")
            raise RuntimeError(
                f"LLM returned empty content: {detail} "
                f"(provider={self._config.provider.value}, model={self._config.model})"
            )
        usage = _usage_details(response)
        self._tracer.record_success(observation, content, usage)
        _record_usage(self._config, trace_context, usage)
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


def _langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def _usage_details(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    usage_details: dict[str, int] = {}
    for source_key, target_key in (
        ("prompt_tokens", "input"),
        ("completion_tokens", "output"),
        ("total_tokens", "total"),
    ):
        value = getattr(usage, source_key, None)
        if value is not None:
            usage_details[target_key] = value

    # Nested detail blocks (OpenAI; absent on Ollama). cached_tokens is the
    # caching signal — cached input reads bill at ~0.1x; reasoning_tokens is
    # gpt-5 thinking, billed as output. Surfaced so the report can split them.
    cached = _nested_detail(usage, "prompt_tokens_details", "cached_tokens")
    if cached is not None:
        usage_details["cached_input"] = cached
    reasoning = _nested_detail(usage, "completion_tokens_details", "reasoning_tokens")
    if reasoning is not None:
        usage_details["reasoning"] = reasoning

    return usage_details or None


def _nested_detail(usage: Any, block: str, field: str) -> int | None:
    """Read usage.<block>.<field>, tolerating a missing block/field (e.g. Ollama)."""
    details = getattr(usage, block, None)
    if details is None:
        return None
    value = getattr(details, field, None)
    return value if isinstance(value, int) else None


def _record_usage(
    config: ModelConfig,
    trace_context: LLMTraceContext | None,
    usage: dict[str, int] | None,
) -> None:
    """Append this call's token usage to the ledger (best-effort, never raises)."""
    if trace_context is None or usage is None:
        return
    try:
        record_usage(
            UsageRecord(
                run_id=trace_context.run_id,
                stage_name=trace_context.stage_name,
                pipeline_kind=trace_context.pipeline_kind,
                provider=config.provider.value,
                model=config.model,
                input_tokens=usage.get("input", 0),
                cached_input_tokens=usage.get("cached_input", 0),
                output_tokens=usage.get("output", 0),
                reasoning_tokens=usage.get("reasoning", 0),
                total_tokens=usage.get("total", 0),
                iteration=trace_context.iteration,
            )
        )
    except Exception as exc:  # noqa: BLE001 - observability must not break LLM calls
        _LOG.warning("Usage ledger record failed: %s", exc)
