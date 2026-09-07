from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm.openai_provider import OpenAIResponsesProvider
from app.llm.router import LLMRouter, RouterPolicy


@dataclass(frozen=True, slots=True)
class LLMRuntimeStatus:
    enabled: bool
    configured: bool
    provider: str
    cheap_model: str
    strong_model: str
    send_candidate_pii: bool
    reason: str


def runtime_status(settings: dict[str, Any]) -> LLMRuntimeStatus:
    config = settings.get("llm") or {}
    provider_name = str(config.get("provider", "openai"))
    enabled = config.get("enabled") is True
    provider = OpenAIResponsesProvider() if provider_name == "openai" else None
    configured = provider is not None and provider.configured
    if not enabled:
        reason = "LLM_DISABLED"
    elif provider is None:
        reason = "LLM_PROVIDER_UNSUPPORTED"
    elif not configured:
        reason = "OPENAI_API_KEY_MISSING"
    else:
        reason = "READY"
    return LLMRuntimeStatus(
        enabled=enabled,
        configured=configured,
        provider=provider_name,
        cheap_model=str(config.get("cheap_model", "gpt-5-nano")),
        strong_model=str(config.get("strong_model", "gpt-5-mini")),
        send_candidate_pii=config.get("send_candidate_pii") is True,
        reason=reason,
    )


def build_router(settings: dict[str, Any]) -> LLMRouter | None:
    status = runtime_status(settings)
    if status.reason != "READY":
        return None
    config = settings["llm"]
    policy = RouterPolicy(
        max_input_chars=int(config.get("max_input_chars", 12_000)),
        max_output_tokens=int(config.get("max_output_tokens", 2_000)),
        daily_cost_limit_usd=float(config.get("daily_cost_limit_usd", 5.0)),
        cheap_models=(status.cheap_model,),
        strong_models=(status.strong_model,),
    )
    return LLMRouter(OpenAIResponsesProvider(), policy=policy)
