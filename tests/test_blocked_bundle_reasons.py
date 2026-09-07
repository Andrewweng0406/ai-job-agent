import json

from scripts.live_dry_run import _write_blocked_bundle
from app.applications.browser_capture import BrowserCaptureResult
from app.models.enums import JobFamily
from app.models.job import Job


def test_blocked_bundle_preserves_runtime_failure_reason(tmp_path):
    job = Job("1", "test", "Test", "Remote", "x", "fixture", "https://x", "https://x", "fixture", JobFamily.UNKNOWN)
    actions = [{"success": False, "reason": "LEASE_LOST"}]
    _write_blocked_bundle(tmp_path, "run", "lever", job, "app", "worker", 1,
                          "https://x", "https://x", "title", BrowserCaptureResult([], "<html>"), "<html>", actions)
    report = json.loads((tmp_path / "report.json").read_text())
    assert "LEASE_LOST" in report["blocking_reasons"]
