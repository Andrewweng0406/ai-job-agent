"""Gate G — the remaining gaps after Codex 6020308 ("Harden auditable Greenhouse evidence runs").

Codex fixed the plumbing: lease fencing + approval gate in GreenhouseLiveDryRunRunner, sanitized
transcript, job-id-preserving DOM sanitizer, run.sqlite3 gitignored. What is still missing is an
*exercised* approved-autofill live run. These tests pin that.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

ARTIFACTS = Path("artifacts")


def _bundles():
    return sorted(p for p in ARTIFACTS.glob("phase43-anthropic-*") if p.is_dir())


def _latest_bundle():
    bs = _bundles()
    assert bs, "no evidence bundle committed"
    return bs[-1]  # -v5 sorts last


# --------------------------------------------------------------- fixed plumbing (regression guards)
def test_live_runner_fences_the_lease_around_browser_mutations():
    src = inspect.getsource(__import__("app.applications.greenhouse_live", fromlist=["x"]))
    assert src.count("_assert_lease(") >= 4, "lease must be re-checked around nav and autofill"
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


def test_latest_sanitized_transcript_carries_the_marker_and_redacts_sensitive_values():
    b = _latest_bundle()
    payload = json.loads((b / "transcript.sanitized.json").read_text())
    assert payload.get("sanitized") is True, f"{b.name}: no sanitized marker"
    for f in payload.get("fields", []):
        key = str(f.get("canonical_key") or "").lower()
        if f.get("legal_sensitive") or key in {"email", "phone", "contact.email", "contact.phone"}:
            assert f.get("value") in (None, "[REDACTED]"), f"{b.name}: sensitive value not redacted: {f}"


def test_latest_dom_sanitizer_keeps_the_job_requisition_id():
    d = _latest_bundle() / "dom.sanitized.html"
    text = d.read_text()
    assert len(text) > 50_000
    assert "4461450008" in text, "job id redacted by the sanitizer"
    assert "REDACTED_PHONE" not in text, "over-redaction"


def test_no_committed_bundle_dom_contains_over_redaction_tokens():
    for b in _bundles():
        d = b / "dom.sanitized.html"
        if d.exists() and len(d.read_text()) > 50_000:
            assert "REDACTED_PHONE" not in d.read_text(), f"{b.name}: over-redacted DOM"


# =============================================================== STILL OPEN

def test_autofill_path_requires_a_lease_identity():
    src = inspect.getsource(__import__("app.applications.greenhouse_live", fromlist=["x"]))
    # _assert_lease currently: `if payload.worker_id is None or payload.lease_epoch is None: return`
    # A hardened runner would REQUIRE worker_id+lease_epoch whenever autofill is enabled.
    assert "autofill" in src and "worker_id is None" in src
    guard = src.split("if payload.autofill", 1)[1][:600]
    assert "worker_id" in guard or "lease_epoch" in guard, "autofill guard does not require a lease identity"


def test_autofill_apply_rechecks_lease_between_fields():
    src = inspect.getsource(__import__("app.applications.browser_autofill", fromlist=["x"]))
    assert "lease" in src.lower()


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW GATE-G: no approved-autofill live run has been evidenced — every committed bundle is approval_status=not_approved_capture_only with attempted_field_count=0")
def test_an_approved_autofill_bundle_exists_with_exercised_differential():
    ok = []
    for b in _bundles():
        r = b / "report.json"
        s = b / "safety.json"
        if not (r.exists() and s.exists()):
            continue
        report = json.loads(r.read_text())
        safety = json.loads(s.read_text())
        if report.get("approval_status") == "approved" and safety.get("attempted_field_count", 0) > 0 \
           and safety.get("mismatch_count") == 0 and report.get("submit_invocation_count") == 0:
            ok.append(b.name)
    assert ok, "need >=1 bundle: approved, fields actually filled, zero mismatch, zero submit"


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2-24b: before_fill.png is a plain viewport shot, not a #application_form region capture; and capture-only runs have no real before/after")
def test_before_and_after_screenshots_are_form_region_and_differ():
    import hashlib

    for b in _bundles():
        bf, af = b / "before_fill.png", b / "after_fill.png"
        if not (bf.exists() and af.exists()):
            continue
        # a form-region 'after' capture is large (full page/form); 'before' should also be > viewport-sized
        assert bf.stat().st_size > 300_000, f"{b.name}: before_fill looks like a viewport shot ({bf.stat().st_size} B)"
        assert hashlib.md5(bf.read_bytes()).hexdigest() != hashlib.md5(af.read_bytes()).hexdigest()
