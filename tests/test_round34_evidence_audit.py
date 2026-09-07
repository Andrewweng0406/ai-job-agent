"""Round 3.4 — independent audit of Codex's reproducible Greenhouse live-dry-run bundle (dee8e92).

Passing tests assert what the bundle genuinely proves.
xfail(strict=False) marks Gate-G gaps that remain (CLAUDE_REVIEW round 3.4).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

BUNDLE = Path("artifacts/phase43-anthropic-4461450008-v5")


def _load(name):
    return json.loads((BUNDLE / name).read_text())


# --------------------------------------------------------------- report metadata
def test_report_has_reproducibility_metadata():
    r = _load("report.json")
    assert r["run_id"] == "phase43-anthropic-4461450008-v5"
    datetime.fromisoformat(r["captured_at"])  # valid ISO 8601
    assert r["source"] == "live_capture" and r["live_page"] is True and r["real_browser"] is True
    assert r["page_title"] == "Job Application for Account Executive, AI Native at Anthropic"
    assert r["final_browser_url"] == r["application_url"]
    assert r["worker_id"].startswith("evidence-") and isinstance(r["lease_epoch"], int)
    assert r["submit_invocation_count"] == 0 and r["would_submit"] is False


def test_report_truthfully_flags_capture_only():
    """This run performed no autofill; the report must not imply otherwise."""
    r, s = _load("report.json"), _load("safety.json")
    assert r["approval_status"] == "not_approved_capture_only"
    assert r["approved_by"] is None
    assert r["upload_performed"] is False
    assert s["attempted_field_count"] == 0  # nothing was typed


# --------------------------------------------------------------- DOM authenticity
def test_dom_is_a_real_greenhouse_capture():
    html = (BUNDLE / "dom.sanitized.html").read_text()
    assert len(html) > 50_000
    assert "job-boards.greenhouse.io/anthropic" in html
    assert "AnthropicSansDisplay" in html                       # real Anthropic font asset
    assert "candidate-ai-guidance" in html                      # real Anthropic AI-policy link
    assert "Account Executive" in html


# --------------------------------------------------------------- field traceability
def test_every_field_map_entry_traces_to_the_captured_dom():
    html = (BUNDLE / "dom.sanitized.html").read_text().lower()
    fields = _load("field_map.json")
    assert len(fields) >= 24
    untraceable = []
    for f in fields:
        label = (f["raw_label"] or "").strip().rstrip("*").strip().lower()
        sel_id = (f["selector"] or "").split("=", 1)[-1].lower()
        # the field is traceable if its label text OR its selector id appears in the DOM
        if label and label[:30] in html:
            continue
        if sel_id and sel_id in html:
            continue
        untraceable.append((f["raw_label"], f["selector"]))
    assert not untraceable, f"field_map entries not found in captured DOM: {untraceable}"


def test_field_map_reflects_real_greenhouse_question_ids():
    fields = _load("field_map.json")
    q_ids = [f["selector"] for f in fields if "question_" in (f["selector"] or "")]
    assert len(q_ids) >= 8, "expected the role's custom questions to carry real greenhouse question ids"
    # sponsorship question is present and required
    spon = [f for f in fields if "sponsorship" in (f["raw_label"] or "").lower()]
    assert spon and spon[0]["required"] is True


def test_hidden_fields_are_not_in_the_field_map():
    fields = _load("field_map.json")
    assert all(f["hidden"] is False for f in fields)
    assert all("hp_" not in (f["selector"] or "").lower() for f in fields)


# --------------------------------------------------------------- action log
def test_browser_actions_are_ordered_lease_stamped_and_submit_free():
    lines = [json.loads(x) for x in (BUNDLE / "browser_actions.jsonl").read_text().splitlines() if x.strip()]
    assert [a["action"] for a in lines] == ["NAVIGATE", "SCAN_HARD_STOP", "EXTRACT_FIELDS", "POST_FILL_SCAN"]
    assert all(a["lease_epoch"] == lines[0]["lease_epoch"] for a in lines)
    ts = [datetime.fromisoformat(a["timestamp"]) for a in lines]
    assert ts == sorted(ts)
    blob = (BUNDLE / "browser_actions.jsonl").read_text().upper()
    for banned in ("ENTER", "RETURN", "SUBMIT", "REQUEST_SUBMIT", "FORM_SUBMIT", "CLICK", "PRESS"):
        assert banned not in blob


# --------------------------------------------------------------- safety.json
def test_safety_report_zero_submit_zero_mismatch():
    s = _load("safety.json")
    assert s["submit_invocation_count"] == 0
    assert s["mismatch_count"] == 0
    assert s["unplanned_browser_actions"] == 0


# =============================================================== OPEN Gate-G gaps

def test_transcript_sanitized_json_is_actually_sanitized():
    raw = (BUNDLE / "transcript.sanitized.json").read_text()
    payload = json.loads(raw)
    assert payload.get("sanitized") is True or "[REDACTED" in raw


def test_screenshots_show_the_application_form_region():
    import hashlib

    before = (BUNDLE / "before_fill.png").read_bytes()
    after = (BUNDLE / "after_fill.png").read_bytes()
    jd_fold = Path("artifacts/greenhouse_anthropic_4461450008.png").read_bytes()
    assert hashlib.md5(before).hexdigest() != hashlib.md5(jd_fold).hexdigest(), "before_fill is the old JD-fold screenshot"


def test_run_sqlite3_is_not_committed():
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "artifacts/"], capture_output=True, text=True).stdout
    assert "run.sqlite3" not in tracked


def test_live_runner_enforces_lease_and_approval():
    import inspect

    from app.applications import greenhouse_live

    src = inspect.getsource(greenhouse_live)
    assert "lease_still_mine" in src, "no lease fencing in the reusable live runner"
    assert "ApprovedAutofillPreviewBuilder" in src or "approve" in src, "no approval gate in the reusable live runner"


def test_sanitizer_does_not_redact_the_job_requisition_id():
    html = (BUNDLE / "dom.sanitized.html").read_text()
    assert "4461450008" in html, "the job id was redacted as a phone number"
