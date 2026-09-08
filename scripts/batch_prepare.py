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
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.applications.batch_prepare import build_batch_record
from app.applications.browser_capture import BrowserFieldCapture
from app.applications.form_engine import InputKind, resolve_form_field
from app.applications.standard_answers import StandardAnswers
from app.database.repository import JobAgentRepository
from app.llm.essay import EssayWriter
from app.llm.runtime import build_router
from app.resumes.profile import CandidateProfile
from app.utils.config import load_yaml
from app.utils.env import load_dotenv
from scripts.assisted_apply import _fill_one, _role_from_title
from scripts.live_dry_run import _sanitize_html


def _wait_for_form(page, timeout_ms: int = 15_000) -> bool:
    """SPA ATS boards (Ashby, some Greenhouse) load the form after DOMContentLoaded."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    for sel in ('form input:not([type=hidden])', 'form textarea',
                'input[type=email]', 'input[name*="name" i]', '[role="textbox"]'):
        try:
            page.wait_for_selector(sel, timeout=4_000, state="visible")
            return True
        except Exception:
            continue
    return False


def _slug(company: str, url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{company}-{url.rsplit('/', 1)[-1]}".lower()).strip("-")[:80]


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

    todo = _candidates(repo, args.limit)
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
                capture = BrowserFieldCapture().capture(page, ats_type=row["ats_type"] or "greenhouse")
                if sum(1 for r_ in capture.fields) < 4:
                    (out / "record.json").write_text(json.dumps(
                        {"blocked": True, "reasons": ["TOO_FEW_FIELDS_CAPTURED"],
                         "company": row["company"], "role": row["position"],
                         "apply_url": row["apply_url"]}, indent=2))
                    print(f"  THIN    {row['company']} — only {len(capture.fields)} fields captured")
                    attention += 1
                    continue
                (out / "dom.sanitized.html").write_text(_sanitize_html(page.content()), encoding="utf-8")
                if capture.human_required:
                    (out / "record.json").write_text(json.dumps(
                        {"blocked": True, "reasons": capture.blocking_reasons,
                         "company": row["company"], "role": row["position"],
                         "apply_url": row["apply_url"]}, indent=2))
                    print(f"  BLOCKED  {row['company']} — {capture.blocking_reasons}")
                    attention += 1
                    continue

                resolutions = [resolve_form_field(f, profile, resume_pdf, resume_validated=bool(resume_pdf))
                               for f in capture.fields]
                record = build_batch_record(
                    company=row["company"], role=_role_from_title(title, row["position"]),
                    apply_url=row["apply_url"], ats=row["ats_type"] or "greenhouse",
                    resume_pdf=resume_pdf, raw_fields=capture.fields, resolutions=resolutions,
                    standard_answers=std, jd_excerpt=row["description"] or "", essay_writer=essay_writer,
                )

                # fill every mappable field; a per-field failure is noted, not fatal
                for selector, value in record.fill_map().items():
                    try:
                        _fill_one(page, selector, value)
                    except Exception as fx:  # noqa: BLE001
                        record.blockers.append(f"could not fill '{selector}' ({type(fx).__name__})")
                # résumé upload — best effort
                if resume_pdf:
                    for r in resolutions:
                        if r.kind == InputKind.FILE:
                            try:
                                page.locator(r.selector.replace("id=", "#", 1)).set_input_files(resume_pdf)
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
