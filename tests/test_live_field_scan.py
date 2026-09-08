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
