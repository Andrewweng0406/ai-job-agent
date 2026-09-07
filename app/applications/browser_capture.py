from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import re

from app.applications.form_engine import RawFormField
from app.applications.html_form_extractor import HtmlFormFieldExtractor


class PageLike(Protocol):
    def content(self) -> str: ...

    def screenshot(self, *, path: str) -> None: ...


@dataclass(frozen=True, slots=True)
class BrowserCaptureResult:
    fields: list[RawFormField]
    html: str
    blocking_reasons: list[str] = field(default_factory=list)
    screenshot_path: str | None = None

    @property
    def human_required(self) -> bool:
        return bool(self.blocking_reasons)


class BrowserFieldCapture:
    CAPTCHA_PATTERN = re.compile(
        r"\b(captcha|hcaptcha|recaptcha|turnstile|cf-turnstile|cf-challenge|"
        r"challenges\.cloudflare\.com|verify\s+you\s+are\s+human|checking\s+your\s+browser)\b",
        re.I,
    )
    MFA_PATTERN = re.compile(r"\b(mfa|multi-factor|two-factor|verification\s+code|one-time\s+password|otp)\b", re.I)
    EMAIL_VERIFICATION_PATTERN = re.compile(r"\b(email\s+verification|verify\s+your\s+email|verification\s+link)\b", re.I)

    def __init__(self, extractor: HtmlFormFieldExtractor | None = None) -> None:
        self.extractor = extractor or HtmlFormFieldExtractor()

    def capture(
        self,
        page: PageLike,
        *,
        ats_type: str,
        screenshot_path: str | Path | None = None,
    ) -> BrowserCaptureResult:
        html = page.content()
        reasons = []
        if self.CAPTCHA_PATTERN.search(html):
            reasons.append("CAPTCHA")
        if self.EMAIL_VERIFICATION_PATTERN.search(html):
            reasons.append("EMAIL_VERIFICATION")
        elif self.MFA_PATTERN.search(html):
            reasons.append("MFA")
        saved_screenshot = None
        if screenshot_path is not None:
            saved_screenshot = str(screenshot_path)
            Path(saved_screenshot).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=saved_screenshot)
        fields = [] if reasons else self.extractor.extract(html, ats_type)
        return BrowserCaptureResult(
            fields=fields,
            html=html,
            blocking_reasons=reasons,
            screenshot_path=saved_screenshot,
        )
