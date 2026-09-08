#!/usr/bin/env python3
"""Prepare a batch of applications for review: fill every mappable field + an essay
draft in a headless browser, screenshot the filled form, and write a review record.
Nothing is submitted.

  python3 scripts/batch_prepare.py --limit 10 \
      --resume-pdf data/resumes/andrew_weng_master.pdf

Records land in review/batch/<slug>/ : record.json, filled.png, dom.sanitized.html
Approve/skip them in the dashboard; approving opens a headed browser you submit in.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.applications.batch_prepare import resolve_scanned
from app.applications.live_field_scan import scan_form
from app.applications.standard_answers import StandardAnswers
from app.database.repository import JobAgentRepository
from app.llm.essay import EssayWriter
from app.llm.runtime import build_router
from app.resumes.profile import CandidateProfile
from app.utils.config import load_yaml
from app.utils.env import load_dotenv
from scripts.assisted_apply import _fill_one, _harvest_options, _role_from_title, _verify_filled
from scripts.live_dry_run import _sanitize_html


def _wait_for_form(page, timeout_ms: int = 15_000) -> bool:
    """SPA ATS boards (Ashby, some Greenhouse) load the form after DOMContentLoaded."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    for sel in ('input:not([type=hidden]):not([type=submit]):not([type=button])',
                'textarea', 'form input:not([type=hidden])', 'form textarea',
                'input[type=email]', 'input[name*="name" i]', '[role="textbox"]'):
        try:
            page.wait_for_selector(sel, timeout=4_000, state="visible")
            return True
        except Exception:
            continue
    return False


def _slug(company: str, url: str) -> str:
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    identity = segments[-1] if segments else "application"
    if identity.lower() in {"application", "apply"} and len(segments) > 1:
        identity = segments[-2]
    return re.sub(r"[^a-z0-9]+", "-", f"{company}-{identity}".lower()).strip("-")[:80]


def _normalize_apply_url(url: str) -> str:
    """A company careers page that only proxies Greenhouse (…?gh_jid=N) never
    renders the real form; jump straight to the Greenhouse board."""
    m = re.search(r"[?&]gh_jid=(\d+)", url)
    if not m:
        return url
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    if "greenhouse.io" in host:
        return url
    token = host.split(".")[0]  # e.g. stripe.com -> stripe
    return f"https://job-boards.greenhouse.io/{token}/jobs/{m.group(1)}"


def _candidates(repo: JobAgentRepository, limit: int) -> list[dict]:
    with repo.connect() as conn:
        rows = conn.execute(
            """SELECT a.application_id, a.company, a.position, j.apply_url, j.ats_type, j.description
               FROM applications a JOIN jobs j ON j.id = a.job_id
               WHERE a.status IN ('QUEUED','READY') AND j.apply_url LIKE 'http%'
               ORDER BY COALESCE(a.queued_at, a.discovered_at) ASC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in rows]


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--company", default=None, help="only prepare applications whose company contains this")
    ap.add_argument("--application-id", default=None, help="prepare one exact application record")
    ap.add_argument("--profile", default="config/candidate_profile.local.yaml")
    ap.add_argument("--standard-answers", default="config/standard_answers.local.yaml")
    ap.add_argument("--resume-pdf", default="data/resumes/andrew_weng_master.pdf")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--out-root", default="review/batch")
    ap.add_argument("--timeout-ms", type=int, default=30_000)
    args = ap.parse_args()

    settings = load_yaml(args.settings)
    repo = JobAgentRepository(settings.get("database_path", "data/job_agent.sqlite3"))
    profile = CandidateProfile.from_yaml(args.profile)
    std = StandardAnswers.from_yaml(args.standard_answers)
    router = build_router(settings)
    essay_writer = None if router is None else EssayWriter(
        router, profile, model=str((settings.get("llm") or {}).get("strong_model", "gpt-5-mini"))
    )
    resume_pdf = args.resume_pdf if Path(args.resume_pdf).is_file() else ""
    if not resume_pdf:
        print(f"! résumé not found at {args.resume_pdf} — records will note a missing resume")

    candidate_limit = 1000 if args.application_id else (args.limit if not args.company else 200)
    todo = _candidates(repo, candidate_limit)
    if args.application_id:
        todo = [row for row in todo if row["application_id"] == args.application_id]
    if args.company:
        todo = [r for r in todo if args.company.lower() in (r["company"] or "").lower()][:args.limit]
    if not todo:
        print("nothing QUEUED/READY to prepare")
        return 0
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    ready = attention = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for row in todo:
            row["apply_url"] = _normalize_apply_url(row["apply_url"])
            slug = _slug(row["company"], row["apply_url"])
            out = out_root / slug
            out.mkdir(parents=True, exist_ok=True)
            page = browser.new_context().new_page()
            try:
                page.goto(row["apply_url"], wait_until="domcontentloaded", timeout=args.timeout_ms)
                title = page.title()
                if not _wait_for_form(page):
                    (out / "record.json").write_text(json.dumps(
                        {"blocked": True, "reasons": ["FORM_DID_NOT_LOAD"],
                         "company": row["company"], "role": row["position"],
                         "apply_url": row["apply_url"]}, indent=2))
                    print(f"  NO FORM  {row['company']} — application form did not render")
                    attention += 1
                    continue
                page.wait_for_timeout(2500)  # let lazy field groups render
                scanned = scan_form(page)
                option_selectors = {
                    f"q{i}": field.selector for i, field in enumerate(scanned)
                    if field.kind in {"combobox", "select"} and not field.options
                }
                harvested = _harvest_options(page, option_selectors)
                scanned = [
                    replace(field, options=harvested.get(f"q{i}", field.options))
                    for i, field in enumerate(scanned)
                ]
                if len(scanned) < 4:
                    (out / "record.json").write_text(json.dumps(
                        {"blocked": True, "reasons": ["TOO_FEW_FIELDS_CAPTURED"],
                         "company": row["company"], "role": row["position"],
                         "apply_url": row["apply_url"]}, indent=2))
                    print(f"  THIN    {row['company']} — only {len(scanned)} fields scanned")
                    attention += 1
                    continue
                (out / "dom.sanitized.html").write_text(_sanitize_html(page.content()), encoding="utf-8")

                record = resolve_scanned(
                    company=row["company"], role=_role_from_title(title, row["position"]),
                    apply_url=row["apply_url"], ats=row["ats_type"] or "greenhouse",
                    resume_pdf=resume_pdf, scanned=scanned, profile=profile,
                    standard_answers=std, jd_excerpt=row["description"] or "", essay_writer=essay_writer,
                )

                # fill every mappable field; a per-field failure is noted, not fatal
                for selector, value in record.fill_map().items():
                    try:
                        _fill_one(page, selector, value)
                        _verify_filled(page, selector, value)
                    except Exception as fx:  # noqa: BLE001
                        record.blockers.append(
                            f"could not verify fill '{selector}' ({type(fx).__name__}: {fx})"
                        )
                # résumé upload — fallback to the first file input if nothing mapped it
                if resume_pdf and not any(f.kind == "file" and f.value for f in record.fields):
                    try:
                        fi = page.locator('input[type=file]').first
                        if fi.count():
                            fi.set_input_files(resume_pdf)
                        else:
                            record.blockers.append("resume upload needs you (no file input found)")
                    except Exception as up_exc:  # noqa: BLE001
                        record.blockers.append(f"resume upload needs you ({type(up_exc).__name__})")
                page.screenshot(path=str(out / "filled.png"), full_page=True)
                (out / "record.json").write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))

                flag = "READY   " if record.ready else "ATTENTION"
                ready += record.ready
                attention += not record.ready
                print(f"  {flag} {row['company']} — {record.role}"
                      + ("" if record.ready else f"  ({'; '.join(record.blockers[:2])})"))
            except Exception as exc:  # noqa: BLE001
                print(f"  ERROR   {row['company']}: {type(exc).__name__}: {exc}")
                attention += 1
            finally:
                page.context.close()
        browser.close()

    print(f"\nprepared {len(todo)}: {ready} ready for review, {attention} need attention -> review/batch/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
