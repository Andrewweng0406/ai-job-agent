import pytest

from app.applications.live_field_scan import scan_form


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def test_scanner_uses_control_specific_labels_and_does_not_copy_form_text(page):
    page.set_content("""
      <form class="application_form_field_wrapper">
        <div><label for="first_name">First Name*</label><input id="first_name" required></div>
        <div><label for="email">Email*</label><input id="email" required></div>
        <section>Lots of unrelated application instructions and attachment text.</section>
      </form>
    """)

    fields = scan_form(page)

    assert [(field.selector, field.label) for field in fields] == [
        ("id=first_name", "First Name*"),
        ("id=email", "Email*"),
    ]


def test_scanner_uses_aria_labelledby_for_react_combobox(page):
    page.set_content("""
      <div class="application_form_field_wrapper">
        <span id="school-label">School*</span>
        <input id="school--0" role="combobox" aria-labelledby="school-label" required>
      </div>
    """)

    fields = scan_form(page)

    assert len(fields) == 1
    assert fields[0].label == "School*"
    assert fields[0].selector == "id=school--0"


def test_scanner_distinguishes_resume_from_cover_letter_upload(page):
    page.set_content("""
      <label for="resume">Attach</label><input id="resume" type="file">
      <label for="cover_letter">Attach</label><input id="cover_letter" type="file">
    """)

    fields = scan_form(page)

    assert [(field.selector, field.label) for field in fields] == [
        ("id=resume", "Resume/CV"),
        ("id=cover_letter", "Cover Letter"),
    ]


def test_scanner_groups_ashby_options_under_question_label(page):
    page.set_content("""
      <fieldset class="ashby-application-form-input-radio-group">
        <label class="ashby-application-form-question-title required">Work Authorization Status</label>
        <div><label for="any">Can work for any employer</label><input id="any" name="auth" type="radio"></div>
        <div><label for="current">Can work for current employer</label><input id="current" name="auth" type="radio"></div>
      </fieldset>
    """)

    fields = scan_form(page)

    assert len(fields) == 1
    assert fields[0].label == "Work Authorization Status"
    assert fields[0].selector == "name=auth"
    assert fields[0].required
    assert fields[0].options == ["Can work for any employer", "Can work for current employer"]


def test_optional_sms_consent_does_not_inherit_required_phone_label(page):
    page.set_content("""
      <div class="ashby-application-form-field-entry">
        <label class="required" for="phone">Phone</label>
        <input id="phone" required>
        <div class="consentRadioGroup">
          <label><input type="radio" name="communicationConsent" value="given">Yes - I consent</label>
          <label><input type="radio" name="communicationConsent" value="notGiven">No - I do not consent</label>
        </div>
      </div>
    """)

    fields = scan_form(page)
    consent = next(field for field in fields if field.selector == "name=communicationConsent")

    assert consent.label == "SMS communication consent"
    assert not consent.required


def test_scanner_reads_nested_lever_custom_question_label(page):
    page.set_content("""
      <li class="application-question custom-question">
        <div>
          <div class="application-label full-width multiple-choice">
            <div class="text">May we use an AI notetaker?<span class="required">✱</span></div>
          </div>
          <div class="application-field required-field"><ul><li><label>
            <input type="radio" name="cards[id][field0]" value="Yes" required>
            <span>Yes</span>
          </label></li><li><label>
            <input type="radio" name="cards[id][field0]" value="No" required>
            <span>No</span>
          </label></li></ul></div>
        </div>
      </li>
    """)

    fields = scan_form(page)

    assert len(fields) == 1
    assert fields[0].label == "May we use an AI notetaker?✱"
    assert fields[0].options == ["Yes", "No"]


def test_scanner_preserves_long_structured_consent_prompt(page):
    prompt = "May we process this interview transcript? " + ("Detailed policy text. " * 20)
    page.set_content(f"""
      <li class="application-question custom-question">
        <div><div class="application-label"><div class="text">{prompt}</div></div>
          <div><label><input type="radio" name="consent" value="Yes" required>Yes</label>
          <label><input type="radio" name="consent" value="No" required>No</label></div>
        </div>
      </li>
    """)

    fields = scan_form(page)

    assert fields[0].label == prompt.strip()
    assert len(fields[0].label) > 280
