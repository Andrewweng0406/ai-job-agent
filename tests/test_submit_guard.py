"""Submit-guard attack (Round 3.1 WS12).

Aggressively try to make a dry run reach a final submit. Even with every green light
(all fields valid, would_submit True, no human tasks, valid resume, no CAPTCHA, READY),
the irreversible action must be unreachable.
"""
from __future__ import annotations

import pytest

from app.applications.ats_dom_dry_run import AtsDomDryRunAdapter
from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.applications.greenhouse_live import GreenhouseLiveDryRunInput, GreenhouseLiveDryRunRunner
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import ResumeArtifact
from app.resumes.profile import CandidateFact, CandidateProfile

GREEN_LIGHT_FORM = """
<html><body><form id="application_form" action="/applications">
  <label for="first_name">First Name *</label><input id="first_name" name="job_application[first_name]" required>
  <label for="last_name">Last Name *</label><input id="last_name" name="job_application[last_name]" required>
  <label for="email">Email *</label><input id="email" name="job_application[email]" required>
  <label for="resume">Resume/CV *</label><input id="resume" type="file" name="job_application[resume]" required>
  <button id="submit_app" type="submit">Submit Application</button>
</form></body></html>
"""


class _Page:
    def __init__(self, html):
        self.html = html
        self.gotos = []

    def content(self):
        return self.html

    def goto(self, url, *, wait_until, timeout):
        self.gotos.append((url, wait_until, timeout))

    def screenshot(self, *, path):
        pass


def _profile():
    return CandidateProfile(
        candidate_id="cand", schema_version=2,
        facts={
            "name.full": CandidateFact("name.full", "identity", "Jane Student", required=True),
            "contact.email": CandidateFact("contact.email", "contact", "jane@example.test", required=True),
        },
        application_answers={"work_authorized_us": "Yes", "requires_sponsorship_now_or_future": "Yes"},
    )


def _seed(tmp_path):
    repo = JobAgentRepository(tmp_path / "sg.sqlite3")
    repo.initialize()
    job = Job(external_job_id="1", company_id="acme", company_name="Acme", title="Data Analyst",
              location="Remote", description="x", source="greenhouse",
              source_url="https://boards.greenhouse.io/acme/jobs/1",
              apply_url="https://boards.greenhouse.io/acme/jobs/1", ats_type="greenhouse",
              job_family=JobFamily.DATA_ANALYTICS)
    job.id = repo.upsert_job(job)
    app = Application(job_id=job.id, company="Acme", position="Data Analyst", location="Remote",
                      job_family=JobFamily.DATA_ANALYTICS, source="greenhouse", ats_type="greenhouse",
                      status=ApplicationStatus.READY)
    app_id = repo.insert_application(app)
    repo.insert_resume_artifact(ResumeArtifact(
        resume_id="r1", job_id=job.id, persona=Persona.DATA, base_version="t",
        generated_at="2026-09-07T00:00:00+00:00", changes={}, validation_status="VALIDATED",
        file_path="data/resumes/r1.pdf", file_hash="sha256:abc"))
    repo.attach_resume_to_application(app_id, "r1")
    return repo, job, app_id


def test_green_light_dry_run_never_calls_submit(tmp_path):
    repo, job, app_id = _seed(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=False)
    result = adapter.dry_run(
        page=_Page(GREEN_LIGHT_FORM), application_id=app_id, job=job, profile=_profile(),
        resume_id="r1", resume_path="data/resumes/r1.pdf", resume_hash="sha256:abc",
        resume_validation_status="VALIDATED", persona="DATA",
    )
    assert result.status == ApplicationStatus.READY
    assert result.dry_run and result.dry_run.transcript.would_submit is True
    assert adapter.submit_call_count == 0
    assert repo.get_application_status(app_id) == ApplicationStatus.READY


def test_adapter_submit_method_raises_and_counts(tmp_path):
    repo, _job, _app_id = _seed(tmp_path)
    adapter = AtsDomDryRunAdapter(repo, ats_type="greenhouse", real_submission_enabled=False)
    with pytest.raises(RuntimeError):
        adapter.submit()
    assert adapter.submit_call_count == 1


def test_live_runner_refuses_real_submission_enabled(tmp_path):
    repo, job, app_id = _seed(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=True)  # someone flipped it
    runner = GreenhouseLiveDryRunRunner(adapter, playwright_factory=lambda: _FakePW(_Page(GREEN_LIGHT_FORM)))
    payload = GreenhouseLiveDryRunInput(
        application_id=app_id, job=job, profile=_profile(),
        resume_id="r1", resume_path="data/resumes/r1.pdf", resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
    )
    with pytest.raises(RuntimeError, match="real_submission_enabled"):
        runner.run(payload)


def test_live_runner_navigates_to_the_apply_url(tmp_path):
    repo, job, app_id = _seed(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=False)
    page = _Page(GREEN_LIGHT_FORM)
    runner = GreenhouseLiveDryRunRunner(adapter, playwright_factory=lambda: _FakePW(page))
    payload = GreenhouseLiveDryRunInput(
        application_id=app_id, job=job, profile=_profile(),
        resume_id="r1", resume_path="data/resumes/r1.pdf", resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
        autofill=False,  # WS11: exercise the read-only path
    )
    result = runner.run(payload)
    assert page.gotos == [(job.apply_url, "domcontentloaded", 30_000)]
    assert adapter.submit_call_count == 0
    assert result.dry_run.status in {ApplicationStatus.READY, ApplicationStatus.HUMAN_REQUIRED}


# --- DryRunBrowserAutofill: no submit surface + differential check ---
def test_dry_run_autofill_has_no_submit_operation():
    from app.applications import browser_autofill

    af = browser_autofill.DryRunBrowserAutofill()
    assert not any(
        "submit" in name.lower() for name in dir(af) if not name.startswith("_")
    ), "the dry-run autofill must expose no submit operation"
    src = _module_source(browser_autofill)
    for banned in ("requestSubmit", "form.submit(", ".submit()", 'click("[type=submit]"'):
        assert banned not in src, f"autofill references a submit primitive: {banned}"


def test_dry_run_autofill_raises_on_transcript_mismatch():
    from app.applications.browser_autofill import DryRunBrowserAutofill
    from app.applications.form_engine import FormFieldResolution, FormFieldStatus, InputKind

    res = FormFieldResolution(
        label="First Name", selector="id=first_name", kind=InputKind.TEXT, required=True,
        status=FormFieldStatus.FILLED, canonical_key="personal.first_name", value="Jane",
    )
    page = _RecordingPage({'[id="first_name"]': "Bob"})  # the field ends up with a different value
    with pytest.raises(RuntimeError, match="BROWSER_TRANSCRIPT_MISMATCH"):
        DryRunBrowserAutofill().apply(page, [res], expected_resume_hash="sha256:abc")


def test_dry_run_autofill_never_presses_enter_or_keys_that_can_submit():
    from app.applications.browser_autofill import DryRunBrowserAutofill
    from app.applications.form_engine import FormFieldResolution, FormFieldStatus, InputKind

    res = FormFieldResolution(
        label="How did you hear about us?", selector="id=source", kind=InputKind.SELECT, required=True,
        status=FormFieldStatus.FILLED, canonical_key="source", value="Company website",
    )
    page = _RecordingPage({"id=source": "Company website"}, role="combobox")
    DryRunBrowserAutofill().apply(page, [res], expected_resume_hash="sha256:abc")
    assert page.key_presses == [], f"autofill pressed keys on a live form: {page.key_presses}"


def _module_source(mod) -> str:
    import inspect

    return inspect.getsource(mod)


class _RecordingLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def fill(self, value):
        self.page.values[self.selector] = self.page.forced.get(self.selector, value)

    def select_option(self, *, label=None):
        self.page.values[self.selector] = self.page.forced.get(self.selector, label)

    def set_checked(self, checked):
        self.page.checked[self.selector] = checked

    def set_input_files(self, path):
        self.page.values[self.selector] = path

    def press(self, key):
        self.page.key_presses.append((self.selector, key))

    def get_attribute(self, name):
        return self.page.role if name == "role" else None

    def input_value(self):
        return self.page.values.get(self.selector, "")

    def is_checked(self):
        return self.page.checked.get(self.selector, False)


class _RecordingPage:
    def __init__(self, forced=None, role=None):
        self.forced = forced or {}
        self.role = role
        self.values = {}
        self.checked = {}
        self.key_presses = []

    def locator(self, selector):
        return _RecordingLocator(self, selector)


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    def new_context(self):
        return self

    def new_page(self):
        return self._page

    def close(self):
        pass


class _FakeChromium:
    def __init__(self, page):
        self._page = page

    def launch(self, *, headless):
        return _FakeBrowser(self._page)


class _FakePW:
    def __init__(self, page):
        self.chromium = _FakeChromium(page)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
