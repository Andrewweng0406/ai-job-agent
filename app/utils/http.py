from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import json
import logging
import random
import threading
import time


@dataclass(frozen=True, slots=True)
class HttpClientConfig:
    timeout_seconds: float = 20.0
    user_agent: str = "AutonomousNewGradJobAgent/0.1 (+local development; read-only discovery)"
    retries: int = 2
    backoff_seconds: float = 0.5
    per_host_requests_per_second: float = 1.0
    jitter_seconds: float = 0.1


class HttpClientError(RuntimeError):
    pass


class JsonHttpClient:
    _lock = threading.Lock()
    _next_allowed_at_by_host: dict[str, float] = {}

    def __init__(self, config: HttpClientConfig | None = None) -> None:
        self.config = config or HttpClientConfig()
        self.logger = logging.getLogger(__name__)

    def get_json(self, url: str) -> Any:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }
        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            self._respect_host_rate_limit(url)
            request = Request(url, headers=headers, method="GET")
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw)
            except HTTPError as exc:
                last_error = exc
                retry_after = _retry_after_seconds(exc)
                self.logger.warning("HTTP GET failed", extra={"status": getattr(exc, "code", None)})
                if attempt < self.config.retries:
                    delay = retry_after if retry_after is not None else self._backoff_delay(attempt)
                    time.sleep(delay)
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                self.logger.warning("HTTP GET failed")
                if attempt < self.config.retries:
                    time.sleep(self._backoff_delay(attempt))
        raise HttpClientError(f"GET {url} failed: {last_error}") from last_error

    def _respect_host_rate_limit(self, url: str) -> None:
        if self.config.per_host_requests_per_second <= 0:
            return
        host = urlsplit(url).netloc
        interval = 1.0 / self.config.per_host_requests_per_second
        with self._lock:
            now = time.monotonic()
            next_allowed = self._next_allowed_at_by_host.get(host, now)
            sleep_for = max(0.0, next_allowed - now)
            self._next_allowed_at_by_host[host] = max(now, next_allowed) + interval
        if sleep_for:
            time.sleep(sleep_for)

    def _backoff_delay(self, attempt: int) -> float:
        jitter = random.uniform(0, self.config.jitter_seconds) if self.config.jitter_seconds else 0
        return self.config.backoff_seconds * (2**attempt) + jitter


def _retry_after_seconds(exc: HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
