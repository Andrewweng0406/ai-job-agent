from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMProvider(Protocol):
    def complete(self, *, model: str, prompt: str, max_tokens: int) -> str: ...


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    stage0_required: bool = True
    max_input_chars: int = 12_000
    max_output_tokens: int = 2_000
    daily_cost_limit_usd: float = 5.0


@dataclass(frozen=True, slots=True)
class LLMUsage:
    stage: str
    model: str
    input_chars: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    usage: LLMUsage


class LLMRouter:
    """Fail-closed provider boundary; callers must prove deterministic gating."""

    def __init__(self, provider: LLMProvider, *, policy: RouterPolicy | None = None) -> None:
        self.provider = provider
        self.policy = policy or RouterPolicy()
        self.spent_usd = 0.0
        self.usage: list[LLMUsage] = []

    def complete(self, *, stage: str, model: str, prompt: str,
                 stage0_passed: bool, estimated_cost_usd: float = 0.0,
                 max_tokens: int | None = None) -> LLMResponse:
        if self.policy.stage0_required and not stage0_passed:
            raise RuntimeError("LLM_STAGE0_GATE_REQUIRED")
        if not prompt.strip():
            raise ValueError("LLM_PROMPT_EMPTY")
        if len(prompt) > self.policy.max_input_chars:
            raise ValueError("LLM_PROMPT_TOO_LARGE")
        if estimated_cost_usd < 0 or self.spent_usd + estimated_cost_usd > self.policy.daily_cost_limit_usd:
            raise RuntimeError("LLM_DAILY_BUDGET_EXCEEDED")
        limit = min(max_tokens or self.policy.max_output_tokens, self.policy.max_output_tokens)
        text = self.provider.complete(model=model, prompt=prompt, max_tokens=limit)
        usage = LLMUsage(stage, model, len(prompt), limit, estimated_cost_usd)
        self.spent_usd += estimated_cost_usd
        self.usage.append(usage)
        return LLMResponse(text, usage)
