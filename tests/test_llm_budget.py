import pytest

from app.llm.budget import SQLiteDailyBudget
from app.llm.router import LLMRouter, RouterPolicy


class _Provider:
    def complete(self, *, model, prompt, max_tokens):
        return "ok"


def test_daily_budget_is_shared_across_router_instances(tmp_path):
    path = tmp_path / "usage.sqlite3"
    policy = RouterPolicy(daily_cost_limit_usd=1.0)
    first = LLMRouter(_Provider(), policy=policy, daily_budget=SQLiteDailyBudget(path))
    first.complete(
        stage="2", model="custom", prompt="one", stage0_passed=True,
        estimated_cost_usd=0.6,
    )
    second = LLMRouter(_Provider(), policy=policy, daily_budget=SQLiteDailyBudget(path))
    with pytest.raises(RuntimeError, match="LLM_DAILY_BUDGET_EXCEEDED"):
        second.complete(
            stage="2", model="custom", prompt="two", stage0_passed=True,
            estimated_cost_usd=0.6,
        )


def test_budget_reconciles_reserved_amount_to_actual(tmp_path):
    ledger = SQLiteDailyBudget(tmp_path / "usage.sqlite3")
    ledger.reserve(0.8, 1.0)
    ledger.reconcile(0.8, 0.2, 1.0)
    assert ledger.spent_today() == pytest.approx(0.2)
