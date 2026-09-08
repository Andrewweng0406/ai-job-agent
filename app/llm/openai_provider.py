from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.llm.router import ProviderResult


class OpenAIResponsesProvider:
    """Minimal no-retry client for bounded, text-only Responses API calls."""

    def __init__(self, *, api_key: str | None = None,
                 base_url: str = "https://api.openai.com/v1",
                 timeout_seconds: float = 30.0) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def complete(self, *, model: str, prompt: str, max_tokens: int) -> ProviderResult:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY_MISSING")
        # Reasoning models spend part of max_output_tokens on hidden reasoning; keep
        # that small for these short structured tasks and give the visible answer room.
        payload = {"model": model, "input": prompt,
                   "max_output_tokens": max_tokens, "store": False,
                   "reasoning": {"effort": "low"}}
        request = Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json",
                     "User-Agent": "ai-job-agent/0.1"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"OPENAI_API_HTTP_ERROR:{exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            # The request may have completed server-side, so never retry it blindly.
            raise RuntimeError("OPENAI_API_RESULT_UNKNOWN") from exc

        usage = body.get("usage") or {}
        return ProviderResult(
            text=_response_text(body),
            input_tokens=_nonnegative_int(usage.get("input_tokens")),
            output_tokens=_nonnegative_int(usage.get("output_tokens")),
        )


def _response_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    chunks: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict) or item.get("type") == "reasoning":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if not chunks:
        reason = (body.get("incomplete_details") or {}).get("reason")
        if reason == "max_output_tokens":
            raise RuntimeError("OPENAI_API_OUTPUT_TRUNCATED")
        raise RuntimeError("OPENAI_API_TEXT_MISSING")
    return "".join(chunks)


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError("OPENAI_API_USAGE_INVALID")
    return value
