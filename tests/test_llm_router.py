import pytest

from app.llm.router import LLMRouter, RouterPolicy


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
