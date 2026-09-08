from pathlib import Path

import pytest

from scripts.assisted_apply import _fill_one, _filled_values_match, _verify_filled


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
    for selector, value in (("id=name", "Test Candidate"), ("id=auth", "Yes"), ("name=sponsor", "Yes")):
        _fill_one(page, selector, value)
        assert _verify_filled(page, selector, value)


def test_readback_detects_value_replaced_after_fill(page):
    page.set_content('<input id="why">')
    _fill_one(page, "id=why", "Expected essay")
    page.locator("#why").fill("Test Candidate")
    with pytest.raises(RuntimeError, match="FILL_READBACK_MISMATCH"):
        _verify_filled(page, "id=why", "Expected essay")


def test_readback_verifies_uploaded_filename(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-test")
    page.set_content('<input id="resume" type="file">')
    evidence = _fill_one(page, "id=resume", str(resume))
    assert evidence == Path(resume).name
    assert _verify_filled(page, "id=resume", str(resume), action_evidence=evidence) == Path(resume).name


def test_file_upload_evidence_survives_react_unmount(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-test")
    page.set_content('<input id="resume" type="file" onchange="this.remove()">')
    evidence = _fill_one(page, "id=resume", str(resume))

    assert page.locator("#resume").count() == 0
    assert _verify_filled(
        page, "id=resume", str(resume), action_evidence=evidence
    ) == resume.name


def test_readback_handles_greenhouse_react_select(page):
    page.set_content("""
      <div class="select__control">
        <div class="select__value-container">
          <div class="select__single-value">Yes</div>
          <div class="select__input-container"><input id="sponsor" role="combobox"></div>
        </div>
        <button>Toggle flyout</button>
      </div>
    """)
    assert _verify_filled(page, "id=sponsor", "Yes")


def test_phone_country_can_use_exact_clicked_option_as_secondary_evidence(page):
    page.set_content('<input id="country" role="combobox" value="+1">')
    assert _verify_filled(
        page, "id=country", "United States", action_evidence="United States"
    ) == "+1"


def test_secondary_evidence_cannot_hide_an_empty_react_control(page):
    page.set_content('<input id="country" role="combobox" value="">')
    with pytest.raises(RuntimeError, match="FILL_READBACK_MISMATCH"):
        _verify_filled(page, "id=country", "United States", action_evidence="United States")


def test_long_essay_is_never_treated_as_a_filesystem_path():
    essay = "I built reliable data systems. " * 200
    assert _filled_values_match(essay, essay)
