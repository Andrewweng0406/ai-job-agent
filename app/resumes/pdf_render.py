"""HTML -> PDF via the already-installed Playwright Chromium (no new dependency)."""
from __future__ import annotations


def html_to_pdf_bytes(html: str, *, timeout_ms: int = 20_000) -> bytes:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load", timeout=timeout_ms)
            return page.pdf(
                format="Letter",
                print_background=True,
                margin={"top": "0.5in", "bottom": "0.5in", "left": "0.55in", "right": "0.55in"},
            )
        finally:
            browser.close()
