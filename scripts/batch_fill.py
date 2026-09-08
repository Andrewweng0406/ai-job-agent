#!/usr/bin/env python3
"""Open one batch record in a visible browser, fill it from the reviewed values, and
stop. You review the form and click Submit. Nothing here submits.

  python3 scripts/batch_fill.py --record review/batch/<slug> --keep-open-seconds 900
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.applications.batch_prepare import BATCH_RECORD_SCHEMA_VERSION, BatchRecord
from app.applications.batch_answers import BatchAnswersError, load_batch_answers, rebind_fill_map
from app.applications.live_field_scan import scan_form
from scripts.assisted_apply import _fill_one, _verify_filled


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", required=True, help="review/batch/<slug> directory")
    ap.add_argument("--keep-open-seconds", type=int, default=900)
    ap.add_argument("--timeout-ms", type=int, default=30_000)
    args = ap.parse_args()

    rec_path = Path(args.record) / "record.json"
    raw = json.loads(rec_path.read_text())
    if int(raw.get("schema_version", 1)) != BATCH_RECORD_SCHEMA_VERSION:
        print("record is stale; prepare it again")
        return 2
    if raw.get("blocked"):
        print(f"record is blocked: {raw.get('reasons')}")
        return 2
    record = BatchRecord.from_dict(raw)
    if not record.ready:
        try:
            approved = load_batch_answers(rec_path.parent, raw)
        except BatchAnswersError as exc:
            print(f"record has unresolved or failed fields: {exc}")
            return 2
    else:
        approved = None
    print(f"{record.role} @ {record.company}")
    if record.blockers:
        print("NOTE — these still need you in the browser:")
        for b in record.blockers:
            print(f"  - {b}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_context().new_page()
        try:
            page.goto(record.apply_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            page.wait_for_timeout(2_500)
            try:
                fill_map = rebind_fill_map(record, scan_form(page), approved)
            except BatchAnswersError as exc:
                print(f"Form changed or selectors could not be rebound: {exc}")
                return 2
            print(f"{len(fill_map)} fields to fill; résumé: {record.resume_pdf or '(none)'}")
            for selector, value in fill_map.items():
                try:
                    action_evidence = _fill_one(page, selector, value)
                    _verify_filled(page, selector, value, action_evidence=action_evidence)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {selector}: {type(exc).__name__}: {exc}")
                    print("Mapped-field fill failed. Closing without leaving a partial form for submission.")
                    return 2
            print("\nForm filled. NOT submitted. Review it and click Submit yourself.")
            page.wait_for_timeout(max(60, args.keep_open_seconds) * 1000)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
