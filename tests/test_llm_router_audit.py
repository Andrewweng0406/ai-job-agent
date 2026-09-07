"""Reviewer audit of app/llm/router.py — the fail-closed LLM boundary (a258faf).

IMPLEMENTED + TESTED; no live provider. Passing = a guard that works. xfail = a gap
(CLAUDE_REVIEW P2 — self-reported cost, in-memory daily budget, no model-tier enforcement).
"""
from __future__ import annotations

import pytest

from app.llm.router import LLMRouter, RouterPolicy


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

@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2: cost is caller-supplied; estimated_cost_usd=0 bypasses the budget entirely — the router should derive cost from (model, input, output) via a price table")
def test_zero_declared_cost_cannot_bypass_the_budget():
    r = _router(daily_cost_limit_usd=0.01)
    # 1000 calls each declaring $0 -> should NOT all be free
    for _ in range(1000):
        r.complete(stage="3", model="expensive-model", prompt="x" * 5000, stage0_passed=True, estimated_cost_usd=0.0)
    assert r.spent_usd > 0.01, "the router treated 1000 large generations as free"


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2: spent_usd is per-instance/in-memory — 'daily' budget resets every process; needs date-keyed persistence")
def test_daily_budget_persists_across_router_instances():
    RouterPolicy_ = RouterPolicy(daily_cost_limit_usd=1.0)
    a = LLMRouter(_StubProvider(), policy=RouterPolicy_)
    a.complete(stage="1", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=0.9)
    b = LLMRouter(_StubProvider(), policy=RouterPolicy_)  # new process/instance, same day
    with pytest.raises(RuntimeError, match="LLM_DAILY_BUDGET_EXCEEDED"):
        b.complete(stage="1", model="m", prompt="hi", stage0_passed=True, estimated_cost_usd=0.9)


def test_stage1_cannot_use_a_strong_model():
    r = _router()
    with pytest.raises((RuntimeError, ValueError)):
        r.complete(stage="1", model="opus-class-strong", prompt="hi", stage0_passed=True, estimated_cost_usd=0.0)
