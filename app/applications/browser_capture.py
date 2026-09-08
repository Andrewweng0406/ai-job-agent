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
    form_detected: bool = False
    submit_control_detected: bool = False
    posting_closed: bool = False
    validation_errors: list[str] = field(default_factory=list)
    drift_reasons: list[str] = field(default_factory=list)
    # Passive captcha/turnstile markup that ships with a working form and is only
    # challenged on submit. Recorded for the evidence bundle, never a hard stop for
    # a no-submit dry run.
    passive_bot_protection: list[str] = field(default_factory=list)

    @property
    def human_required(self) -> bool:
        return bool(self.blocking_reasons)


class BrowserFieldCapture:
    CAPTCHA_PATTERN = re.compile(
        r"\b(captcha|hcaptcha|recaptcha)\b",
        re.I,
    )
    BOT_WALL_PATTERN = re.compile(
        r"\b(turnstile|cf-turnstile|cf-challenge|challenges\.cloudflare\.com|"
        r"verify\s+you\s+are\s+human|checking\s+your\s+browser|access\s+denied)\b",
        re.I,
    )
    CAPTCHA_WIDGET_PATTERN = re.compile(
        r'<(?:div|iframe)[^>]+class=["\'][^"\']*(?:g-recaptcha|h-captcha)[^"\']*["\']|'
        r'<script[^>]+src=["\'][^"\']*(?:recaptcha|hcaptcha)[^"\']*["\']',
        re.I,
    )
    BOT_WALL_WIDGET_PATTERN = re.compile(
        r'<(?:div|iframe)[^>]+class=["\'][^"\']*(?:cf-turnstile|cf-challenge)[^"\']*["\']',
        re.I,
    )
    MFA_PATTERN = re.compile(r"\b(mfa|multi-factor|two-factor|verification\s+code|one-time\s+password|otp)\b", re.I)
    EMAIL_VERIFICATION_PATTERN = re.compile(r"\b(email\s+verification|verify\s+your\s+email|verification\s+link)\b", re.I)
    CLOSED_PATTERN = re.compile(r"\b(job|position|posting)\s+(is\s+)?(closed|no longer available|has been filled)\b", re.I)

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
        visible_html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
        # Match challenge language against visible *text* only. Tag/class/data-* names
        # and the passive reCAPTCHA/Turnstile snippet that ships on virtually every
        # Greenhouse/Lever form must not by themselves read as an active wall — that
        # snippet is only ever challenged on submit, which a dry run never does.
        visible_text = _plain_text(visible_html)
        form_detected = bool(re.search(r"<form\b", html, re.I))
        # A real *application* form: several inputs, not one stray search box.
        field_element_count = len(re.findall(r"<(input|select|textarea)\b", html, re.I))
        real_form_present = field_element_count >= 3

        reasons: list[str] = []
        passive: list[str] = []
        captcha_widget = bool(self.CAPTCHA_WIDGET_PATTERN.search(html))
        botwall_widget = bool(self.BOT_WALL_WIDGET_PATTERN.search(html))
        # Visible challenge TEXT is always a hard stop — active challenges and
        # interstitials render text to the user.
        if self.CAPTCHA_PATTERN.search(visible_text):
            reasons.append("CAPTCHA")
        elif captcha_widget:
            (passive if real_form_present else reasons).append("CAPTCHA")
        if self.BOT_WALL_PATTERN.search(visible_text):
            reasons.append("BOT_WALL")
        elif botwall_widget:
            (passive if real_form_present else reasons).append("BOT_WALL")
        if self.EMAIL_VERIFICATION_PATTERN.search(visible_text):
            reasons.append("EMAIL_VERIFICATION")
        elif self.MFA_PATTERN.search(visible_text):
            reasons.append("MFA")
        saved_screenshot = None
        if screenshot_path is not None:
            saved_screenshot = str(screenshot_path)
            Path(saved_screenshot).parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=saved_screenshot)
        submit_control_detected = bool(re.search(r"<(button|input)\b[^>]*type=[\"']submit[\"']", html, re.I))
        posting_closed = bool(self.CLOSED_PATTERN.search(html))
        validation_errors = [
            _plain_text(value)
            for value in re.findall(r'<[^>]*(?:role=["\']alert["\']|class=["\'][^"\']*error[^"\']*["\'])[^>]*>(.*?)</[^>]+>', html, re.I | re.S)
            if _plain_text(value)
        ]
        drift_reasons = []
        if not posting_closed and not form_detected:
            drift_reasons.append("MISSING_APPLICATION_FORM")
        if form_detected and not submit_control_detected:
            drift_reasons.append("MISSING_SUBMIT_CONTROL")
        fields = [] if reasons or posting_closed else self.extractor.extract(html, ats_type)
        return BrowserCaptureResult(
            fields=fields,
            html=html,
            blocking_reasons=reasons,
            screenshot_path=saved_screenshot,
            form_detected=form_detected,
            submit_control_detected=submit_control_detected,
            posting_closed=posting_closed,
            validation_errors=validation_errors,
            drift_reasons=drift_reasons,
            passive_bot_protection=passive,
        )


def _plain_text(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())
