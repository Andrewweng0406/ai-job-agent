from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderResult:
    text: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    def complete(
        self, *, model: str, prompt: str, max_tokens: int
    ) -> ProviderResult | str: ...


class DailyBudget(Protocol):
    def reserve(self, amount_usd: float, limit_usd: float) -> None: ...
    def reconcile(self, reserved_usd: float, actual_usd: float,
                  limit_usd: float) -> None: ...


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million_usd: float
    output_per_million_usd: float

    def cost(self, *, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million_usd
            + output_tokens * self.output_per_million_usd
        ) / 1_000_000


DEFAULT_MODEL_PRICES = {
    "gpt-5-nano": ModelPrice(0.05, 0.40),
    "gpt-5-mini": ModelPrice(0.25, 2.00),
}


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    stage0_required: bool = True
    max_input_chars: int = 12_000
    max_output_tokens: int = 2_000
    daily_cost_limit_usd: float = 5.0
    cheap_models: tuple[str, ...] = ("gpt-5-nano",)
    strong_models: tuple[str, ...] = ("gpt-5-mini", "opus-class-strong")
    cheap_only_stages: tuple[str, ...] = ("1", "4", "extract", "validate")


@dataclass(frozen=True, slots=True)
class LLMUsage:
    stage: str
    model: str
    input_chars: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    usage: LLMUsage


class LLMRouter:
    """Fail-closed provider boundary; callers must prove deterministic gating."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        policy: RouterPolicy | None = None,
        model_prices: dict[str, ModelPrice] | None = None,
        daily_budget: DailyBudget | None = None,
        cache_enabled: bool = False,
    ) -> None:
        self.provider = provider
        self.policy = policy or RouterPolicy()
        self.model_prices = model_prices or DEFAULT_MODEL_PRICES
        self.daily_budget = daily_budget
        self.cache_enabled = cache_enabled
        self.spent_usd = 0.0
        self.usage: list[LLMUsage] = []
        self._cache: dict[str, ProviderResult] = {}

    def complete(self, *, stage: str, model: str, prompt: str,
                 stage0_passed: bool, estimated_cost_usd: float | None = None,
                 max_tokens: int | None = None) -> LLMResponse:
        if self.policy.stage0_required and not stage0_passed:
            raise RuntimeError("LLM_STAGE0_GATE_REQUIRED")
        if not prompt.strip():
            raise ValueError("LLM_PROMPT_EMPTY")
        if len(prompt) > self.policy.max_input_chars:
            raise ValueError("LLM_PROMPT_TOO_LARGE")
        if stage.lower() in self.policy.cheap_only_stages and model in self.policy.strong_models:
            raise RuntimeError("LLM_MODEL_TIER_VIOLATION")
        if estimated_cost_usd is not None and estimated_cost_usd < 0:
            raise RuntimeError("LLM_DAILY_BUDGET_EXCEEDED")
        limit = min(max_tokens or self.policy.max_output_tokens, self.policy.max_output_tokens)
        price = self.model_prices.get(model)
        if price is not None:
            preflight_cost = price.cost(
                input_tokens=max(1, len(prompt) // 4), output_tokens=limit
            )
        else:
            # Unknown models are estimated at the most expensive configured rate,
            # never treated as free or allowed to trust a zero caller estimate.
            conservative = ModelPrice(
                max(item.input_per_million_usd for item in self.model_prices.values()),
                max(item.output_per_million_usd for item in self.model_prices.values()),
            )
            conservative_cost = conservative.cost(
                input_tokens=max(1, len(prompt) // 4), output_tokens=limit
            )
            preflight_cost = max(estimated_cost_usd or 0.0, conservative_cost)
        cache_key = hashlib.sha256(f"{model}\0{limit}\0{prompt}".encode()).hexdigest()
        result = self._cache.get(cache_key) if self.cache_enabled else None
        cache_hit = result is not None
        if result is None:
            if self.daily_budget is not None:
                self.daily_budget.reserve(preflight_cost, self.policy.daily_cost_limit_usd)
            elif self.spent_usd + preflight_cost > self.policy.daily_cost_limit_usd:
                raise RuntimeError("LLM_DAILY_BUDGET_EXCEEDED")
            raw = self.provider.complete(model=model, prompt=prompt, max_tokens=limit)
            if isinstance(raw, ProviderResult):
                if raw.input_tokens < 0 or raw.output_tokens < 0:
                    raise ValueError("LLM_PROVIDER_USAGE_INVALID")
                result = raw
            else:
                result = ProviderResult(raw, max(1, len(prompt) // 4), limit)
            if self.cache_enabled:
                self._cache[cache_key] = result

        actual_cost = 0.0 if cache_hit else (
            price.cost(input_tokens=result.input_tokens, output_tokens=result.output_tokens)
            if price is not None else preflight_cost
        )
        if self.daily_budget is not None and not cache_hit:
            self.daily_budget.reconcile(
                preflight_cost, actual_cost, self.policy.daily_cost_limit_usd
            )
        elif self.spent_usd + actual_cost > self.policy.daily_cost_limit_usd:
            raise RuntimeError("LLM_DAILY_BUDGET_EXCEEDED_AFTER_RESPONSE")
        usage = LLMUsage(
            stage, model, len(prompt),
            0 if cache_hit else result.input_tokens,
            0 if cache_hit else result.output_tokens,
            actual_cost, cache_hit,
        )
        self.spent_usd += actual_cost
        self.usage.append(usage)
        return LLMResponse(result.text, usage)
