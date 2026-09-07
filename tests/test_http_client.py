from email.message import Message
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
import io

import pytest

from app.utils import http
from app.utils.http import HttpClientConfig, HttpClientError, JsonHttpClient


def test_get_retries_and_honors_retry_after(monkeypatch):
    calls = []
    sleeps = []
    headers = Message()
    headers["Retry-After"] = "1.25"

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "rate limited", headers, None)
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    client = JsonHttpClient(HttpClientConfig(retries=1, per_host_requests_per_second=0, jitter_seconds=0))

    assert client.get_json("https://api.example.test/jobs") == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [1.25]
    assert calls[0].get_method() == "GET"


def test_get_retries_are_bounded(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise URLError("offline")

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    client = JsonHttpClient(HttpClientConfig(retries=2, per_host_requests_per_second=0, jitter_seconds=0))

    with pytest.raises(HttpClientError):
        client.get_json("https://api.example.test/jobs")
    assert len(calls) == 3


def test_get_retries_5xx_with_http_date_retry_after(monkeypatch):
    calls = []
    sleeps = []
    headers = Message()
    headers["Retry-After"] = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=2))

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 503, "unavailable", headers, None)
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    client = JsonHttpClient(HttpClientConfig(retries=1, per_host_requests_per_second=0, jitter_seconds=0))

    assert client.get_json("https://api.example.test/jobs") == {"ok": True}
    assert len(calls) == 2
    assert len(sleeps) == 1
    assert 0 <= sleeps[0] <= 2.5


def test_get_does_not_retry_ordinary_client_errors(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 404, "missing", Message(), None)

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    client = JsonHttpClient(HttpClientConfig(retries=5, per_host_requests_per_second=0))
    with pytest.raises(HttpClientError):
        client.get_json("https://api.example.test/missing")
    assert len(calls) == 1


def test_post_is_not_blind_retried(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise URLError("post failed after send")

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    client = JsonHttpClient(HttpClientConfig(retries=5, per_host_requests_per_second=0, jitter_seconds=0))

    with pytest.raises(HttpClientError):
        client.post_json("https://api.example.test/apply", {"field": "value"})
    assert len(calls) == 1
    assert calls[0].get_method() == "POST"


def test_per_host_spacing(monkeypatch):
    sleeps = []
    monotonic_values = iter([10.0, 10.2])

    def fake_urlopen(request, timeout):
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    monkeypatch.setattr(http.time, "sleep", sleeps.append)
    monkeypatch.setattr(http.time, "monotonic", lambda: next(monotonic_values))
    http.JsonHttpClient._next_allowed_at_by_host.clear()
    client = JsonHttpClient(HttpClientConfig(retries=0, per_host_requests_per_second=2, jitter_seconds=0))

    client.get_json("https://api.example.test/a")
    client.get_json("https://api.example.test/b")

    assert sleeps == [0.3000000000000007]


def test_timeout_is_wrapped(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    client = JsonHttpClient(HttpClientConfig(retries=0, per_host_requests_per_second=0))

    with pytest.raises(HttpClientError):
        client.get_json("https://api.example.test/jobs")


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.body
