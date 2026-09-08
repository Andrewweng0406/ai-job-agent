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

# A realistic application form (>=3 fields) — enough to distinguish a working
# form page from an interstitial that has replaced the form.
BIG_FORM = (
    "<html><body><form id='application_form'>"
    "<label for='fn'>First Name*</label><input id='fn' name='first_name' required>"
    "<label for='ln'>Last Name*</label><input id='ln' name='last_name' required>"
    "<label for='e'>Email*</label><input id='e' name='email' required>"
    "<label for='p'>Phone</label><input id='p' name='phone'>"
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


def test_passive_recaptcha_script_alongside_a_real_form_is_not_a_hard_stop():
    """Modern Greenhouse/Lever forms ship the reCAPTCHA v3/enterprise snippet on
    every page; it is only challenged on submit, which a dry run never does. A
    passive script next to a working form must not block capture — but it is
    recorded so the evidence bundle still shows the mechanism exists."""
    html = (
        "<html><head><script src='https://www.google.com/recaptcha/api.js?render=SITEKEY'></script></head>"
        "<body>" + BIG_FORM + "</body></html>"
    )
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == []
    assert result.fields
    assert "CAPTCHA" in result.passive_bot_protection


def test_recaptcha_widget_that_replaced_the_form_is_a_hard_stop():
    html = (
        "<html><body><div class='g-recaptcha' data-sitekey='x'></div>"
        "<script src='https://www.google.com/recaptcha/api.js'></script></body></html>"
    )
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert "CAPTCHA" in result.blocking_reasons
    assert result.fields == []


def test_visible_recaptcha_instruction_text_blocks_even_with_a_form():
    html = "<html><body><p>Please complete the reCAPTCHA to continue.</p>" + BIG_FORM + "</body></html>"
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == ["CAPTCHA"]
    assert result.fields == []


def test_inactive_recaptcha_configuration_in_hydration_data_is_not_a_wall():
    html = CLEAN_FORM + '<script>window.config={"GOOGLE_RECAPTCHA_ENDPOINT":"https://www.recaptcha.net/recaptcha/enterprise.js"}</script>'
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == []
    assert result.fields


def test_turnstile_widget_that_replaced_the_page_is_a_bot_wall():
    html = (
        "<html><body><div class='cf-turnstile' data-sitekey='0xABC'></div>"
        "<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>"
        "</body></html>"
    )
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == ["BOT_WALL"]
    assert result.fields == []


def test_passive_turnstile_widget_alongside_a_real_form_is_recorded_not_blocking():
    html = (
        "<html><body><div class='cf-turnstile' data-sitekey='0xABC'></div>"
        "<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>"
        + BIG_FORM + "</body></html>"
    )
    result = BrowserFieldCapture().capture(_Page(html), ats_type="greenhouse")
    assert result.blocking_reasons == []
    assert result.fields
    assert "BOT_WALL" in result.passive_bot_protection
