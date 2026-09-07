from hashlib import sha256

import pytest

from app.applications.browser_autofill import DryRunBrowserAutofill
from app.applications.form_engine import FormFieldResolution, FormFieldStatus, InputKind


def _resolution(selector, kind, value):
    return FormFieldResolution(
        label=selector,
        selector=selector,
        kind=kind,
        required=True,
        status=FormFieldStatus.FILLED,
        value=value,
    )


def test_autofill_uses_exact_plan_and_never_submits(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"safe resume")
    digest = sha256(resume.read_bytes()).hexdigest()
    page = _Page()

    result = DryRunBrowserAutofill().apply(
        page,
        [
            _resolution("id=first_name", InputKind.TEXT, "Jane"),
            _resolution("id=source", InputKind.SELECT, "Company website"),
            _resolution("id=resume", InputKind.FILE, str(resume)),
        ],
        expected_resume_hash=digest,
    )

    assert result.filled_selectors == ["id=first_name", "id=source", "id=resume"]
    assert result.upload_call_count == 1
    assert result.final_submit_call_count == 0
    assert page.submit_calls == 0


def test_autofill_stops_when_browser_value_differs_from_transcript():
    page = _Page(mismatch=True)
    with pytest.raises(RuntimeError, match="BROWSER_TRANSCRIPT_MISMATCH"):
        DryRunBrowserAutofill().apply(
            page,
            [_resolution("id=first_name", InputKind.TEXT, "Jane")],
            expected_resume_hash="unused",
        )


def test_bad_resume_hash_prevents_upload(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"changed")
    page = _Page()
    with pytest.raises(RuntimeError, match="RESUME_ARTIFACT_HASH_MISMATCH"):
        DryRunBrowserAutofill().apply(
            page,
            [_resolution("id=resume", InputKind.FILE, str(resume))],
            expected_resume_hash="0" * 64,
        )
    assert page.locators['[id="resume"]'].upload_calls == 0


class _Locator:
    def __init__(self, mismatch=False):
        self.value = ""
        self.checked = False
        self.mismatch = mismatch
        self.upload_calls = 0

    def fill(self, value):
        self.value = value

    def input_value(self):
        return "different" if self.mismatch else self.value

    def get_attribute(self, name):
        return None

    def select_option(self, *, label):
        self.value = label

    def set_input_files(self, path):
        self.upload_calls += 1
        self.value = path

    def set_checked(self, value):
        self.checked = value

    def is_checked(self):
        return self.checked

    def press(self, key):
        return None


class _Page:
    def __init__(self, mismatch=False):
        self.mismatch = mismatch
        self.locators = {}
        self.submit_calls = 0

    def locator(self, selector):
        locator = self.locators.setdefault(selector, _Locator(self.mismatch))
        return locator
