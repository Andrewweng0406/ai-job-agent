from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import time


@dataclass(frozen=True, slots=True)
class HttpClientConfig:
    timeout_seconds: float = 20.0
    user_agent: str = "AutonomousNewGradJobAgent/0.1 (+local development; read-only discovery)"
    retries: int = 2
    backoff_seconds: float = 0.5


class HttpClientError(RuntimeError):
    pass


class JsonHttpClient:
    def __init__(self, config: HttpClientConfig | None = None) -> None:
        self.config = config or HttpClientConfig()

    def get_json(self, url: str) -> Any:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            request = Request(url, headers=headers, method="GET")
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.config.retries:
                    time.sleep(self.config.backoff_seconds * (2**attempt))
        raise HttpClientError(f"GET {url} failed: {last_error}") from last_error
