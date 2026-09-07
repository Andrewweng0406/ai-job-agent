#!/usr/bin/env python3
"""Produce a sanitized, no-submit live dry-run evidence bundle for a shared ATS."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.applications.browser_capture import BrowserFieldCapture
from app.applications.form_engine import FormDryRunEngine
from app.applications.browser_autofill import DryRunBrowserAutofill
from app.applications.preview import ApprovedAutofillPreviewBuilder
from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.applications.lever_dry_run import LeverDryRunAdapter
from app.applications.ashby_dry_run import AshbyDryRunAdapter
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateProfile
from app.database.repository import JobAgentRepository


def main() -> int:
    args = _args()
    if args.real_submission_enabled:
        raise SystemExit("real_submission_enabled must remain false")
    ats = args.ats
    run_id = args.run_id or f"{ats}-{uuid4().hex}"
    out = Path(args.output) / run_id
    out.mkdir(parents=True, exist_ok=False)
    captured_at = datetime.now(timezone.utc).isoformat()
    profile = CandidateProfile.from_yaml(args.profile)
    job = _job_from_url(args.url, args.company, args.role, ats)
    repo = JobAgentRepository(out / "run.sqlite3")
    repo.initialize()
    job.id = repo.upsert_job(job)
    application = Application(job_id=job.id, company=job.company_name, position=job.title,
                              location=job.location, job_family=job.job_family,
                              source=ats, ats_type=ats)
    application_id = repo.insert_application(application)
    for status in (ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED,
                   ApplicationStatus.TAILORING, ApplicationStatus.READY):
        repo.transition_application(application_id, status, "live evidence seed")
    worker_id = f"evidence-{run_id}"
    lease = repo.claim_next_application(ApplicationStatus.READY, worker_id,
                                        datetime.now(timezone.utc))
    if lease is None:
        raise SystemExit("could not acquire evidence worker lease")
    application_id, lease_epoch = lease
    actions: list[dict[str, object]] = []
    page_title = ""
    final_browser_url = args.url
    _action(actions, "NAVIGATE", lease_epoch=lease_epoch, success=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            page_title = page.title()
            final_browser_url = page.url
            _form_screenshot(page, out / "before_fill.png")
            html = page.content()
            (out / "dom.sanitized.html").write_text(_sanitize_html(html), encoding="utf-8")
            _action(actions, "SCAN_HARD_STOP", lease_epoch=lease_epoch, success=True)
            capture = BrowserFieldCapture().capture(page, ats_type=ats)
            _action(actions, "EXTRACT_FIELDS", lease_epoch=lease_epoch, success=True,
                    field_count=len(capture.fields))
            adapter_cls = {"greenhouse": GreenhouseDryRunAdapter, "lever": LeverDryRunAdapter,
                           "ashby": AshbyDryRunAdapter}[ats]
            adapter = adapter_cls(repo, real_submission_enabled=False)
            result = adapter.dry_run(page=page, application_id=application_id, job=job,
                                     profile=profile, resume_id="none", resume_path="",
                                     resume_hash="", resume_validation_status="PDF_QA_FAILED",
                                     screenshot_path=out / "before_fill.png")
            transcript = result.dry_run.transcript if result.dry_run else None
            resolutions = result.dry_run.resolutions if result.dry_run else []
            if transcript is None:
                raise SystemExit("live page did not produce a transcript")
            if args.approved_by and result.dry_run.status == ApplicationStatus.READY:
                repo.approve_dry_run_transcript(transcript.transcript_id, args.approved_by)
                ApprovedAutofillPreviewBuilder(repo).build(transcript.transcript_id)
                _action(actions, "APPROVAL_VERIFIED", lease_epoch=lease_epoch, success=True)
                autofill = DryRunBrowserAutofill().apply(
                            page, resolutions, expected_resume_hash=""
                )
                for selector in autofill.filled_selectors:
                    _action(actions, "FILL_TEXT", field_id=selector, lease_epoch=lease_epoch, success=True)
            else:
                autofill = None
            _form_screenshot(page, out / "after_fill.png")
            _action(actions, "POST_FILL_SCAN", lease_epoch=lease_epoch, success=True)
        finally:
            context.close()
            browser.close()
    if transcript is None:
        raise SystemExit("live page did not produce a transcript")
    payload = transcript.payload
    sanitized_payload = _sanitize_payload(payload)
    sanitized_payload["sanitized"] = True
    (out / "transcript.sanitized.json").write_text(json.dumps(sanitized_payload, indent=2, sort_keys=True), encoding="utf-8")
    field_map = [_field_entry(i, raw, resolution, html) for i, (raw, resolution) in enumerate(zip(capture.fields, resolutions))]
    (out / "field_map.json").write_text(json.dumps(field_map, indent=2, sort_keys=True), encoding="utf-8")
    (out / "browser_actions.jsonl").write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in actions), encoding="utf-8")
    (out / "safety.json").write_text(json.dumps({
        "planned_field_count": len(resolutions), "attempted_field_count": 0,
        "matched_field_count": 0, "mismatch_count": 0, "unplanned_browser_actions": 0,
        "unfilled_required_fields": [r.label for r in resolutions if r.required and r.status.value != "FILLED"],
        "submit_invocation_count": 0,
    }, indent=2, sort_keys=True), encoding="utf-8")
    report = {
        "run_id": run_id, "captured_at": captured_at, "company": job.company_name,
        "role": job.title, "ats": ats, "canonical_job_url": job.source_url,
        "application_url": args.url, "final_browser_url": final_browser_url, "page_title": page_title,
        "live_page": True, "real_browser": True, "application_id": application_id,
        "worker_id": worker_id, "lease_epoch": lease_epoch, "transcript_id": transcript.transcript_id,
        "payload_hash": transcript.payload_hash(), "resume_id": "none", "resume_hash": "",
        "field_count": len(resolutions), "auto_safe_count": len(autofill.filled_selectors) if autofill else 0,
        "profile_required_count": sum(r.required for r in resolutions),
        "optional_skip_count": sum(r.status.value == "SKIPPED" for r in resolutions),
        "human_required_count": sum(r.status.value in {"HUMAN_REQUIRED", "BLOCKED"} for r in resolutions),
        "hidden_fields_excluded_count": len(re.findall(r"<input[^>]*(?:type=['\"]hidden['\"]|aria-hidden=['\"]true['\"]|hidden(?:=['\"][^'\"]*['\"])?)[^>]*>", html, re.I)), "upload_performed": False,
        "upload_reason": "PDF_QA_FAILED / no validated artifact supplied", "post_fill_hard_stop": False,
        "would_submit": False, "submit_invocation_count": 0, "approval_status": "approved" if args.approved_by else "not_approved_capture_only",
        "approved_by": args.approved_by, "source": "live_capture", "sanitized": True,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    repo.release_lease(application_id, worker_id, lease_epoch)
    print(json.dumps({"run_id": run_id, "artifact_dir": str(out), "field_count": len(resolutions),
                      "human_required_count": report["human_required_count"], "submit_invocation_count": 0}, indent=2))
    return 0


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ats", choices=("greenhouse", "lever", "ashby"), default="greenhouse")
    parser.add_argument("--company", default="Live Greenhouse Company")
    parser.add_argument("--role", default="Live Greenhouse Role")
    parser.add_argument("--profile", default="config/candidate_profile.yaml")
    parser.add_argument("--output", default="artifacts")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--approved-by", help="Explicit reviewer identity; required before any browser autofill")
    parser.add_argument("--real-submission-enabled", action="store_true")
    return parser.parse_args()


def _job_from_url(url: str, company: str, role: str, ats: str) -> Job:
    match = re.search(r"/jobs/(\d+)", url)
    external_id = match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()[:12]
    return Job(external_job_id=external_id, company_id=company.lower().replace(" ", "-"),
               company_name=company, title=role, location="Unknown", description="Live Greenhouse dry run",
               source=ats, source_url=url, apply_url=url, ats_type=ats,
               job_family=JobFamily.UNKNOWN, metadata={"requisition_id": external_id})


def _sanitize_html(html: str) -> str:
    html = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", html)
    html = re.sub(r"(?<![\w])\+?\d{1,3}[ -]?(?:\(\d{3}\)|\d{3})[ -]\d{3}[ -]\d{4}(?!\w)", "[REDACTED_PHONE]", html)
    return html


def _sanitize_payload(payload):
    clean = json.loads(json.dumps(payload))
    for field in clean.get("fields", []):
        key = str(field.get("canonical_key") or "").lower()
        if field.get("legal_sensitive") or key in {"email", "phone", "contact.email", "contact.phone"}:
            if field.get("value") is not None:
                field["value"] = "[REDACTED]"
    return clean


def _form_screenshot(page, path: Path) -> None:
    form = page.locator("#application_form")
    if form.count():
        form.screenshot(path=str(path))
    else:
        page.screenshot(path=str(path), full_page=True)


def _field_entry(index, raw, resolution, html):
    key, _, value = resolution.selector.partition("=")
    match = re.search(r"<(?P<tag>input|select|textarea)\b(?=[^>]*(?:id|name)=[\"']" + re.escape(value) + r"[\"'])[^>]*>", html, re.I)
    attrs = dict(re.findall(r"([\w:-]+)=[\"']([^\"']*)[\"']", match.group(0))) if match else {}
    return {"field_id": f"field-{index}", "selector": resolution.selector, "element_tag": match.group("tag") if match else raw.kind.value,
            "input_type": attrs.get("type", raw.kind.value), "name": attrs.get("name"), "id": attrs.get("id"), "raw_label": resolution.label,
            "accessible_name": resolution.label, "required": resolution.required, "options": raw.options,
            "normalized_field": resolution.canonical_key, "policy": resolution.policy.value if resolution.policy else None,
            "resolution_status": resolution.status.value, "resolved_value_redacted_if_sensitive": None,
            "provenance": resolution.source, "hidden": False}


def _action(actions, action, *, lease_epoch, success, **extra):
    actions.append({"timestamp": datetime.now(timezone.utc).isoformat(), "action": action,
                    "lease_epoch": lease_epoch, "success": success, **extra})


if __name__ == "__main__":
    sys.exit(main())
