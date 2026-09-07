"""Browser capture hard-stop red team (Round 3 WS7/WS12).

CAPTCHA / MFA / bot-wall pages must yield NO extracted fields and a blocking reason.
No solver, no bypass, no retry loop. DOM-drift signals (missing form, renamed controls)
should not be silently filled.
"""
from __future__ import annotations

import pytest

from app.applications.browser_capture import BrowserFieldCapture


class _Page:
    def __init__(self, html: str):
        self._html = html
        self.screens = 0

    def content(self) -> str:
        return self._html

    def screenshot(self, *, path: str) -> None:
        self.screens += 1


CLEAN_FORM = (
    "<html><body><form>"
    "<label for='e'>Email*</label><input id='e' name='email' required>"
    "<label for='r'>Resume</label><input id='r' name='resume' type='file'>"
    "</form></body></html>"
)


@pytest.mark.parametrize(
    "html,reason",
    [
        ("<html><body><div>Please complete the reCAPTCHA to continue.</div>" + CLEAN_FORM + "</body></html>", "CAPTCHA"),
        ("<html><body><h1>Verify you are human</h1>" + CLEAN_FORM + "</body></html>", "BOT_WALL"),
        ("<html><body>Checking your browser before you access the site." + CLEAN_FORM + "</body></html>", "BOT_WALL"),
        ("<html><body>Enter the one-time password we sent to your phone." + CLEAN_FORM + "</body></html>", "MFA"),
        ("<html><body>Two-factor authentication is required." + CLEAN_FORM + "</body></html>", "MFA"),
    ],
)
def test_captcha_or_mfa_page_yields_no_fields_and_blocks(html, reason):
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert reason in result.blocking_reasons
    assert result.fields == [], "no fields may be extracted from a blocked page"
    assert result.human_required is True


def test_clean_form_is_captured():
    result = BrowserFieldCapture().capture(_Page(CLEAN_FORM), ats_type="greenhouse")
    assert result.blocking_reasons == []
    labels = {f.label for f in result.fields}
    assert any("email" in l.lower() for l in labels)
    assert result.human_required is False


def test_screenshot_is_taken_on_blocked_page(tmp_path):
    page = _Page("<html><body>Please solve the captcha." + CLEAN_FORM + "</body></html>")
    shot = tmp_path / "block.png"
    result = BrowserFieldCapture().capture(page, ats_type="greenhouse", screenshot_path=shot)
    assert result.blocking_reasons == ["CAPTCHA"]
    assert page.screens == 1
    assert result.screenshot_path == str(shot)


def test_no_form_on_page_produces_no_fields():
    """DOM drift / wrong page: no form controls -> empty field list, never a fabricated fill."""
    result = BrowserFieldCapture().capture(_Page("<html><body><h1>Page moved</h1><a href='/'>home</a></body></html>"), ats_type="lever")
    assert result.fields == []
    assert result.blocking_reasons == []  # not a captcha; caller must treat empty-required-form as ATS_CHANGED


def test_recaptcha_script_tag_is_detected():
    html = (
        "<html><head><script src='https://www.google.com/recaptcha/api.js?render=SITEKEY'></script></head>"
        "<body>" + CLEAN_FORM + "</body></html>"
    )
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert "CAPTCHA" in result.blocking_reasons


def test_inactive_recaptcha_configuration_in_hydration_data_is_not_a_wall():
    html = CLEAN_FORM + '<script>window.config={"GOOGLE_RECAPTCHA_ENDPOINT":"https://www.recaptcha.net/recaptcha/enterprise.js"}</script>'
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == []
    assert result.fields


def test_turnstile_widget_without_captcha_token_is_detected():
    html = (
        "<html><body><div class='cf-turnstile' data-sitekey='0xABC'></div>"
        "<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>"
        + CLEAN_FORM + "</body></html>"
    )
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == ["BOT_WALL"]
