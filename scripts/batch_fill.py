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

from app.applications.batch_prepare import BatchRecord
from scripts.assisted_apply import _fill_one


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", required=True, help="review/batch/<slug> directory")
    ap.add_argument("--keep-open-seconds", type=int, default=900)
    ap.add_argument("--timeout-ms", type=int, default=30_000)
    args = ap.parse_args()

    rec_path = Path(args.record) / "record.json"
    raw = json.loads(rec_path.read_text())
    if raw.get("blocked"):
        print(f"record is blocked: {raw.get('reasons')}")
        return 2
    record = BatchRecord.from_dict(raw)
    fill_map = record.fill_map()
    print(f"{record.role} @ {record.company}")
    print(f"{len(fill_map)} fields to fill; résumé: {record.resume_pdf or '(none)'}")
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
            for selector, value in fill_map.items():
                try:
                    _fill_one(page, selector, value)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! {selector}: {type(exc).__name__}")
            if record.resume_pdf:
                for f in record.fields:
                    if f.kind == "file":
                        try:
                            page.locator(f.selector.replace("id=", "#", 1)).set_input_files(record.resume_pdf)
                        except Exception:
                            print(f"  ! résumé upload — do it yourself ({f.selector})")
            print("\nForm filled. NOT submitted. Review it and click Submit yourself.")
            page.wait_for_timeout(max(60, args.keep_open_seconds) * 1000)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
