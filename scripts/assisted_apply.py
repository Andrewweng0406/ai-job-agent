#!/usr/bin/env python3
"""Human-in-the-loop assisted apply. Two steps, neither of which submits:

  packet  navigate a live application form, capture it, and write a review packet
          (profile-safe pre-fill + the required questions you must answer).

  fill    after you have written answers.yaml and approved it, open the form,
          fill the safe fields + your answers, screenshot it, and STOP. You
          review the browser window and click Submit yourself.

There is no code path here that submits: no button click on a submit control, no
requestSubmit, no Enter key, no adapter with submission enabled.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.applications.browser_autofill import DryRunBrowserAutofill
from app.applications.browser_capture import BrowserFieldCapture
from app.applications.form_engine import InputKind, resolve_form_field
from app.applications.review_packet import build_review_packet
from app.applications.assisted_answers import load_answers
from app.resumes.profile import CandidateProfile
from scripts.live_dry_run import _sanitize_html, _resolve_profile_path


def _launch(playwright, headed: bool):
    return playwright.chromium.launch(headless=not headed)


def cmd_packet(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = CandidateProfile.from_yaml(_resolve_profile_path(args.profile))

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = _launch(pw, headed=False)
        page = browser.new_context().new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            title = page.title()
            page.screenshot(path=str(out / "before_fill.png"), full_page=True)
            html = page.content()
            capture = BrowserFieldCapture().capture(page, ats_type=args.ats)
        finally:
            browser.close()

    (out / "dom.sanitized.html").write_text(_sanitize_html(html), encoding="utf-8")
    if capture.human_required:
        (out / "packet.json").write_text(json.dumps(
            {"blocked": True, "reasons": capture.blocking_reasons, "url": args.url}, indent=2))
        print(f"BLOCKED: {capture.blocking_reasons} — see {out}")
        return 2

    resolutions = [resolve_form_field(f, profile, args.resume_pdf or "", resume_validated=bool(args.resume_pdf))
                   for f in capture.fields]
    role = _role_from_title(title, args.role)
    packet = build_review_packet(
        company=args.company, role=role, apply_url=args.url, ats=args.ats,
        raw_fields=capture.fields, resolutions=resolutions,
    )
    # field_id -> selector, needed by the fill step
    selectors = {f"q{i}": r.selector for i, r in enumerate(resolutions)
                 if r.status.value in {"HUMAN_REQUIRED", "BLOCKED"}}
    (out / "field_selectors.json").write_text(json.dumps(selectors, indent=2, sort_keys=True))
    (out / "packet.json").write_text(json.dumps(packet.to_dict(), indent=2, sort_keys=True))
    (out / "packet.md").write_text(packet.to_markdown(), encoding="utf-8")

    print(packet.to_markdown())
    print(f"\nWrote {out}/packet.md — fill in {out}/answers.yaml and run: "
          f"assisted_apply.py fill --packet {out}")
    return 0


def cmd_fill(args) -> int:
    packet_dir = Path(args.packet)
    packet_raw = json.loads((packet_dir / "packet.json").read_text())
    if packet_raw.get("blocked"):
        print("packet is blocked; cannot fill")
        return 2
    from app.applications.review_packet import ReviewPacket, SafeField, OpenQuestion
    packet = ReviewPacket(
        company=packet_raw["company"], role=packet_raw["role"], apply_url=packet_raw["apply_url"],
        ats=packet_raw["ats"],
        safe_prefill=[SafeField(**s) for s in packet_raw["safe_prefill"]],
        needs_your_answer=[OpenQuestion(**q) for q in packet_raw["needs_your_answer"]],
        optional_skipped=packet_raw["optional_skipped"],
        blocked=[OpenQuestion(**q) for q in packet_raw["blocked"]],
        resume_fact_ids=packet_raw.get("resume_fact_ids", []),
    )
    approved = load_answers(args.answers or (packet_dir / "answers.yaml"), packet)
    selectors = json.loads((packet_dir / "field_selectors.json").read_text())
    answer_by_selector = {selectors[fid]: val for fid, val in approved.answers.items() if fid in selectors}
    profile = CandidateProfile.from_yaml(_resolve_profile_path(args.profile))

    print(f"Approved by {approved.approved_by} at {approved.approved_at}")
    print(f"Safe pre-fill: {len(packet.safe_prefill)} fields; your answers: {len(answer_by_selector)} fields")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = _launch(pw, headed=args.headed)
        page = browser.new_context().new_page()
        try:
            page.goto(packet.apply_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            capture = BrowserFieldCapture().capture(page, ats_type=packet.ats)
            if capture.human_required:
                print(f"BLOCKED on re-navigation: {capture.blocking_reasons}")
                return 2
            resolutions = [resolve_form_field(f, profile, args.resume_pdf or "",
                                              resume_validated=bool(args.resume_pdf))
                           for f in capture.fields]
            filled = DryRunBrowserAutofill().apply(page, resolutions, expected_resume_hash=_hash(args.resume_pdf))
            for selector, value in answer_by_selector.items():
                _fill_one(page, selector, value)
            page.screenshot(path=str(packet_dir / "after_fill.png"), full_page=True)
            print(f"\nFilled {len(filled.filled_selectors)} profile fields + {len(answer_by_selector)} of your answers.")
            print("The form has NOT been submitted. Review it and click Submit yourself.")
            if args.headed:
                input("\nPress Enter here to close the browser once you are done...")
        finally:
            browser.close()
    return 0


def _fill_one(page, selector: str, value: str) -> None:
    """fill / select / check only — never a click on a submit control, never Enter."""
    loc = page.locator(_css(selector))
    if loc.count() == 0:
        print(f"  ! selector not found, skipped: {selector}")
        return
    tag = (loc.evaluate("el => el.tagName") or "").lower()
    input_type = (loc.get_attribute("type") or "").lower()
    if tag == "select":
        loc.select_option(label=value)
    elif input_type in {"checkbox", "radio"}:
        loc.check()
    else:
        loc.fill(value)


def _css(selector: str) -> str:
    key, sep, val = selector.partition("=")
    if sep and key in {"id", "name", "data-testid", "aria-label"}:
        return f'[{key}="{val}"]'
    return selector


def _role_from_title(page_title: str, fallback: str) -> str:
    m = re.search(r"Job Application for (.+?) at .+$", page_title or "", re.I)
    return m.group(1).strip() if m else fallback


def _hash(pdf_path: str | None) -> str:
    if not pdf_path:
        return ""
    import hashlib
    return "sha256:" + hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("packet")
    pk.add_argument("--url", required=True)
    pk.add_argument("--company", required=True)
    pk.add_argument("--role", default="")
    pk.add_argument("--ats", choices=("greenhouse", "lever", "ashby"), default="greenhouse")
    pk.add_argument("--profile", default="config/candidate_profile.yaml")
    pk.add_argument("--resume-pdf")
    pk.add_argument("--out", required=True)
    pk.add_argument("--timeout-ms", type=int, default=30_000)
    pk.set_defaults(func=cmd_packet)

    fl = sub.add_parser("fill")
    fl.add_argument("--packet", required=True)
    fl.add_argument("--answers")
    fl.add_argument("--profile", default="config/candidate_profile.yaml")
    fl.add_argument("--resume-pdf")
    fl.add_argument("--headed", action="store_true")
    fl.add_argument("--timeout-ms", type=int, default=30_000)
    fl.set_defaults(func=cmd_fill)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
