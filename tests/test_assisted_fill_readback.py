from pathlib import Path

import pytest

from scripts.assisted_apply import _fill_one, _verify_filled


@pytest.fixture
def page():
    playwright = pytest.importorskip("playwright.sync_api").sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    try:
        yield page
    finally:
        browser.close()
        playwright.stop()


def test_readback_verifies_text_select_and_radio(page):
    page.set_content("""
      <label for="name">Name</label><input id="name">
      <label for="auth">Authorization</label>
      <select id="auth"><option>Select</option><option>Yes</option><option>No</option></select>
      <fieldset><legend>Sponsorship</legend>
        <label><input type="radio" name="sponsor" value="yes">Yes</label>
        <label><input type="radio" name="sponsor" value="no">No</label>
      </fieldset>
    """)
    for selector, value in (("id=name", "Andrew Weng"), ("id=auth", "Yes"), ("name=sponsor", "Yes")):
        _fill_one(page, selector, value)
        assert _verify_filled(page, selector, value)


def test_readback_detects_value_replaced_after_fill(page):
    page.set_content('<input id="why">')
    _fill_one(page, "id=why", "Expected essay")
    page.locator("#why").fill("Andrew Weng")
    with pytest.raises(RuntimeError, match="FILL_READBACK_MISMATCH"):
        _verify_filled(page, "id=why", "Expected essay")


def test_readback_verifies_uploaded_filename(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-test")
    page.set_content('<input id="resume" type="file">')
    _fill_one(page, "id=resume", str(resume))
    assert _verify_filled(page, "id=resume", str(resume)) == Path(resume).name
