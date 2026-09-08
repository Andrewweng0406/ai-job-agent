"""Gate G — the Greenhouse live no-submit dry-run milestone.

Plumbing (regression guards): lease fencing + approval gate in the runner, sanitized
transcript, job-id-preserving DOM sanitizer, run.sqlite3 gitignored.

Milestone (now met): at least one committed evidence bundle from a real Greenhouse
application form where the approved autofill actually populated profile-safe fields in
a live browser, with a real before/after differential, zero transcript<->browser
mismatch, and zero submit invocations. Partial ("partial_safe") mode is acceptable —
real forms always carry a required question the profile cannot answer, and a human
still owns those before any submission.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

ARTIFACTS = Path("artifacts")


def _bundles():
    seen = {}
    for pattern in ("phase43-anthropic-*", "phase-gateg-*", "phase-greenhouse-*"):
        for p in ARTIFACTS.glob(pattern):
            if p.is_dir():
                seen[p.name] = p
    return [seen[k] for k in sorted(seen)]


def _load(bundle, name):
    path = bundle / name
    return json.loads(path.read_text()) if path.exists() else None


# --------------------------------------------------------------- fixed plumbing
def test_live_runner_fences_the_lease_around_browser_mutations():
    src = inspect.getsource(__import__("app.applications.greenhouse_live", fromlist=["x"]))
    assert src.count("_assert_lease(") >= 4
    assert "lease_still_mine" in src
    assert 'RuntimeError("LEASE_LOST")' in src


def test_live_runner_requires_an_approved_transcript_for_autofill():
    src = inspect.getsource(__import__("app.applications.greenhouse_live", fromlist=["x"]))
    assert "approved_transcript_id" in src
    assert "ApprovedAutofillPreviewBuilder" in src
    assert "Live autofill requires approved_transcript_id" in src


def test_run_sqlite3_is_gitignored_and_untracked():
    import subprocess

    assert "artifacts/**/run.sqlite3" in Path(".gitignore").read_text()
    tracked = subprocess.run(["git", "ls-files", "artifacts/"], capture_output=True, text=True).stdout
    assert "run.sqlite3" not in tracked


def test_sanitized_transcripts_carry_the_marker_and_redact_sensitive_values():
    checked = 0
    for b in _bundles():
        payload = _load(b, "transcript.sanitized.json")
        if payload is None or not payload.get("fields"):
            continue
        checked += 1
        assert payload.get("sanitized") is True, f"{b.name}: no sanitized marker"
        for f in payload["fields"]:
            if f.get("status") == "FILLED":
                assert f.get("value") in (None, "[REDACTED]"), f"{b.name}: raw value leaked: {f}"
    assert checked, "no sanitized transcript with fields found"


def test_no_committed_bundle_dom_contains_over_redaction_tokens():
    for b in _bundles():
        d = b / "dom.sanitized.html"
        if d.exists() and len(d.read_text()) > 50_000:
            assert "REDACTED_PHONE" not in d.read_text(), f"{b.name}: over-redacted DOM"


# =============================================================== MILESTONE MET
def _exercised_bundles():
    ok = []
    for b in _bundles():
        report, safety = _load(b, "report.json"), _load(b, "safety.json")
        if not report or not safety:
            continue
        if (
            report.get("approval_status") == "approved"
            and report.get("real_browser") is True
            and report.get("live_page") is True
            and safety.get("attempted_field_count", 0) > 0
            and safety.get("matched_field_count", 0) == safety.get("attempted_field_count", 0)
            and safety.get("mismatch_count") == 0
            and report.get("submit_invocation_count") == 0
            and report.get("would_submit") is False
        ):
            ok.append(b)
    return ok


def test_an_approved_autofill_bundle_exists_with_an_exercised_differential():
    assert _exercised_bundles(), \
        "need >=1 bundle: approved, fields actually filled in a live browser, zero mismatch, zero submit"


def test_exercised_bundles_have_a_real_before_after_screenshot_differential():
    for b in _exercised_bundles():
        bf, af = b / "before_fill.png", b / "after_fill.png"
        assert bf.exists() and af.exists(), f"{b.name}: missing screenshots"
        assert bf.stat().st_size > 20_000, f"{b.name}: before_fill is not a real capture"
        assert af.stat().st_size > 20_000, f"{b.name}: after_fill is not a real capture"
        assert hashlib.md5(bf.read_bytes()).hexdigest() != hashlib.md5(af.read_bytes()).hexdigest(), \
            f"{b.name}: before and after are identical"


def test_exercised_bundles_never_recorded_a_submit_or_would_submit():
    for b in _exercised_bundles():
        report = _load(b, "report.json")
        assert report["submit_invocation_count"] == 0
        assert report["would_submit"] is False
        if report.get("autofill_mode") == "partial_safe":
            assert _load(b, "safety.json")["unfilled_required_fields"], \
                f"{b.name}: partial run must leave human-required fields unfilled"
