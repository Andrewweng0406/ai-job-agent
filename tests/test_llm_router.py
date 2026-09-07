import pytest

from app.llm.router import LLMRouter, ModelPrice, ProviderResult, RouterPolicy


class Provider:
    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return '{"ok": true}'


def test_router_requires_stage_zero_before_spending():
    provider = Provider()
    with pytest.raises(RuntimeError, match="STAGE0"):
        LLMRouter(provider).complete(stage="extract", model="cheap", prompt="job", stage0_passed=False)
    assert provider.calls == []


def test_router_enforces_prompt_and_daily_budget():
    provider = Provider()
    router = LLMRouter(provider, policy=RouterPolicy(max_input_chars=4, daily_cost_limit_usd=1))
    with pytest.raises(ValueError, match="TOO_LARGE"):
        router.complete(stage="extract", model="cheap", prompt="12345", stage0_passed=True)
    router.complete(stage="extract", model="cheap", prompt="job", stage0_passed=True, estimated_cost_usd=1)
    with pytest.raises(RuntimeError, match="BUDGET"):
        router.complete(stage="extract", model="cheap", prompt="job", stage0_passed=True, estimated_cost_usd=.01)


def test_router_caps_output_tokens_and_records_usage():
    provider = Provider()
    result = LLMRouter(provider).complete(stage="validate", model="cheap", prompt="job",
                                           stage0_passed=True, max_tokens=9999, estimated_cost_usd=.25)
    assert provider.calls[0]["max_tokens"] == 2000
    assert result.usage.estimated_cost_usd == .25


def test_router_uses_provider_tokens_for_cost_and_caches_identical_calls():
    class MeteredProvider(Provider):
        def complete(self, **kwargs):
            self.calls.append(kwargs)
            return ProviderResult("ok", input_tokens=1000, output_tokens=100)

    provider = MeteredProvider()
    router = LLMRouter(provider, model_prices={"cheap": ModelPrice(1.0, 2.0)})
    first = router.complete(
        stage="extract", model="cheap", prompt="job", stage0_passed=True
    )
    second = router.complete(
        stage="extract", model="cheap", prompt="job", stage0_passed=True
    )
    assert first.usage.estimated_cost_usd == pytest.approx(0.0012)
    assert first.usage.cache_hit is False
    assert second.usage.estimated_cost_usd == 0
    assert second.usage.cache_hit is True
    assert len(provider.calls) == 1


def test_router_rejects_strong_model_for_cheap_stage():
    with pytest.raises(RuntimeError, match="MODEL_TIER"):
        LLMRouter(Provider()).complete(
            stage="extract", model="gpt-5-mini", prompt="job", stage0_passed=True
        )
