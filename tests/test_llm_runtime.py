from app.llm.runtime import build_router, runtime_status


def test_runtime_defaults_to_disabled_and_does_not_build_router(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    status = runtime_status({})
    assert status.reason == "LLM_DISABLED"
    assert build_router({}) is None


def test_runtime_reports_missing_key_without_api_call(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = {"llm": {"enabled": True, "provider": "openai"}}
    assert runtime_status(settings).reason == "OPENAI_API_KEY_MISSING"
    assert build_router(settings) is None


def test_runtime_builds_budgeted_router_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    settings = {"llm": {
        "enabled": True,
        "provider": "openai",
        "cheap_model": "gpt-5-nano",
        "strong_model": "gpt-5-mini",
        "daily_cost_limit_usd": 0.25,
        "send_candidate_pii": True,
    }}
    router = build_router(settings)
    assert router is not None
    assert router.policy.daily_cost_limit_usd == 0.25
    assert runtime_status(settings).send_candidate_pii is True
