from __future__ import annotations

import json

import pytest

from app.llm.openai_provider import OpenAIResponsesProvider


class _Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def test_provider_uses_responses_api_without_storage_or_retry(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request, timeout))
        return _Response({
            "output_text": '{"fit": true}',
            "usage": {"input_tokens": 17, "output_tokens": 5},
        })

    monkeypatch.setattr("app.llm.openai_provider.urlopen", fake_urlopen)
    provider = OpenAIResponsesProvider(api_key="test-secret", timeout_seconds=4)
    result = provider.complete(model="gpt-5-nano", prompt="redacted job", max_tokens=80)

    assert result.text == '{"fit": true}'
    assert (result.input_tokens, result.output_tokens) == (17, 5)
    assert len(seen) == 1
    request, timeout = seen[0]
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert json.loads(request.data) == {
        "model": "gpt-5-nano",
        "input": "redacted job",
        "max_output_tokens": 80,
        "store": False,
    }
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert timeout == 4


def test_provider_requires_local_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIResponsesProvider()
    assert provider.configured is False
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY_MISSING"):
        provider.complete(model="gpt-5-nano", prompt="job", max_tokens=20)


def test_provider_extracts_nested_response_text(monkeypatch):
    monkeypatch.setattr(
        "app.llm.openai_provider.urlopen",
        lambda *_args, **_kwargs: _Response({
            "output": [{"content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 2, "output_tokens": 1},
        }),
    )
    result = OpenAIResponsesProvider(api_key="test").complete(
        model="gpt-5-nano", prompt="job", max_tokens=20
    )
    assert result.text == "ok"
