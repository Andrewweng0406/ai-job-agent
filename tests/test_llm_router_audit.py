"""Reviewer audit of app/llm/router.py — the fail-closed LLM boundary (a258faf).

IMPLEMENTED + TESTED; no live provider. Passing = a guard that works. xfail = a gap
(CLAUDE_REVIEW P2 — self-reported cost, in-memory daily budget, no model-tier enforcement).
"""
from __future__ import annotations

import pytest

from app.llm.router import LLMRouter, RouterPolicy
from app.llm.budget import SQLiteDailyBudget


class _StubProvider:
    def __init__(self):
        self.calls = []

    def complete(self, *, model, prompt, max_tokens):
        self.calls.append((model, len(prompt), max_tokens))
        return "ok"


def _router(**pol):
    return LLMRouter(_StubProvider(), policy=RouterPolicy(**pol))


# ---------------------------------------------------------------- guards that work
def test_stage0_gate_is_mandatory():
    r = _router()
    with pytest.raises(RuntimeError, match="LLM_STAGE0_GATE_REQUIRED"):
        r.complete(stage="1", model="m", prompt="hi", stage0_passed=False)


def test_empty_prompt_rejected():
    with pytest.raises(ValueError, match="LLM_PROMPT_EMPTY"):
        _router().complete(stage="1", model="m", prompt="   ", stage0_passed=True)


def test_oversized_prompt_rejected():
    with pytest.raises(ValueError, match="LLM_PROMPT_TOO_LARGE"):
        _router(max_input_chars=10).complete(stage="1", model="m", prompt="x" * 11, stage0_passed=True)


def test_output_tokens_capped_to_policy():
    r = _router(max_output_tokens=100)
    r.complete(stage="1", model="m", prompt="hi", stage0_passed=True, max_tokens=99999)
    assert r.provider.calls[-1][2] == 100  # provider received the policy cap, not 99999


def test_budget_is_fail_closed_when_cost_is_declared():
    r = _router(daily_cost_limit_usd=1.0)
    r.complete(stage="1", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=0.6)
    with pytest.raises(RuntimeError, match="LLM_DAILY_BUDGET_EXCEEDED"):
        r.complete(stage="2", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=0.6)


def test_negative_cost_rejected():
    with pytest.raises(RuntimeError, match="LLM_DAILY_BUDGET_EXCEEDED"):
        _router().complete(stage="1", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=-1)


# ---------------------------------------------------------------- gaps

def test_zero_declared_cost_cannot_bypass_the_budget():
    r = _router(daily_cost_limit_usd=0.01)
    # Repeated calls declaring $0 must hit the derived conservative budget.
    with pytest.raises(RuntimeError, match="LLM_DAILY_BUDGET_EXCEEDED"):
        for _ in range(1000):
            r.complete(stage="3", model="expensive-model", prompt="x" * 5000,
                       stage0_passed=True, estimated_cost_usd=0.0)
    assert r.spent_usd > 0, "the router treated unknown-model generations as free"


def test_daily_budget_persists_across_router_instances(tmp_path):
    RouterPolicy_ = RouterPolicy(daily_cost_limit_usd=1.0)
    ledger_path = tmp_path / "llm-usage.sqlite3"
    a = LLMRouter(
        _StubProvider(), policy=RouterPolicy_,
        daily_budget=SQLiteDailyBudget(ledger_path),
    )
    a.complete(stage="1", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=0.9)
    b = LLMRouter(
        _StubProvider(), policy=RouterPolicy_,
        daily_budget=SQLiteDailyBudget(ledger_path),
    )
    with pytest.raises(RuntimeError, match="LLM_DAILY_BUDGET_EXCEEDED"):
        b.complete(stage="1", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=0.9)


def test_stage1_cannot_use_a_strong_model():
    r = _router()
    with pytest.raises((RuntimeError, ValueError)):
        r.complete(stage="1", model="opus-class-strong", prompt="hi", stage0_passed=True, estimated_cost_usd=0.0)
