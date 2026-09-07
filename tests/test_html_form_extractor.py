from app.applications.form_engine import InputKind
from app.applications.html_form_extractor import HtmlFormFieldExtractor


def test_greenhouse_label_for_fields_are_extracted():
    html = """
    <form id="application_form">
      <div class="field required">
        <label for="first_name">First Name *</label>
        <input id="first_name" name="job_application[first_name]" required />
      </div>
      <div class="field">
        <label for="resume">Resume/CV *</label>
        <input id="resume" type="file" name="job_application[resume]" />
      </div>
      <div class="field">
        <label for="source">How did you hear about us?</label>
        <select id="source" name="job_application[source]">
          <option>Company website</option>
          <option>LinkedIn</option>
        </select>
      </div>
    </form>
    """

    fields = HtmlFormFieldExtractor().extract(html, "greenhouse")

    assert [(field.label, field.kind, field.required) for field in fields] == [
        ("First Name *", InputKind.TEXT, True),
        ("Resume/CV *", InputKind.FILE, True),
        ("How did you hear about us?", InputKind.SELECT, False),
    ]
    assert fields[2].options == ["Company website", "LinkedIn"]


def test_lever_named_fields_and_textarea_are_extracted():
    html = """
    <form class="application-form">
      <div class="application-field required">
        <input name="email" aria-label="Email" aria-required="true" />
      </div>
      <div class="application-question">
        <label for="comments">Additional information</label>
        <textarea id="comments" name="comments"></textarea>
      </div>
    </form>
    """

    fields = HtmlFormFieldExtractor().extract(html, "lever")

    assert fields[0].label == "Email"
    assert fields[0].required
    assert fields[1].label == "Additional information"
    assert fields[1].kind == InputKind.LONG_TEXT


def test_ashby_react_like_fields_are_extracted_from_aria_and_placeholder():
    html = """
    <form>
      <div class="_fieldEntry _required">
        <input name="candidate-name" aria-label="Full Name" aria-required="true" />
      </div>
      <div class="_fieldEntry">
        <input name="linkedin" placeholder="LinkedIn URL" />
      </div>
      <div class="_fieldEntry">
        <label for="sponsor">Will you require sponsorship?</label>
        <select id="sponsor" aria-required="true">
          <option>Yes</option>
          <option>No</option>
        </select>
      </div>
    </form>
    """

    fields = HtmlFormFieldExtractor().extract(html, "ashby")

    assert [field.label for field in fields] == ["Full Name", "LinkedIn URL", "Will you require sponsorship?"]
    assert fields[0].required
    assert fields[2].kind == InputKind.SELECT
    assert fields[2].options == ["Yes", "No"]
