from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import ResumeArtifact
from app.resumes.profile import CandidateFact, CandidateProfile


GREENHOUSE_FORM = """
<html><body>
  <form id="application_form" action="/applications">
    <label for="first_name">First Name *</label>
    <input id="first_name" name="job_application[first_name]" required>
    <label for="last_name">Last Name *</label>
    <input id="last_name" name="job_application[last_name]" required>
    <label for="email">Email *</label>
    <input id="email" name="job_application[email]" required>
    <label for="phone">Phone *</label>
    <input id="phone" name="job_application[phone]" required>
    <label for="resume">Resume/CV *</label>
    <input id="resume" name="job_application[resume]" type="file" required>
    <fieldset>
      <legend>Will you now or in the future require sponsorship?</legend>
      <label for="s_yes">Yes</label><input id="s_yes" type="radio" name="sponsor" value="yes" required>
      <label for="s_no">No</label><input id="s_no" type="radio" name="sponsor" value="no" required>
    </fieldset>
    <label for="source">How did you hear about us?</label>
    <select id="source" name="job_application[source]"><option>Company website</option></select>
    <button id="submit_app" type="submit">Submit Application</button>
  </form>
</body></html>
"""


def test_greenhouse_dom_dry_run_stops_before_submit_when_ready(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=False)

    result = adapter.dry_run(
        page=_Page(GREENHOUSE_FORM),
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
        persona="DATA",
    )

    assert result.status == ApplicationStatus.READY
    assert result.dry_run is not None
    assert result.dry_run.transcript.would_submit
    assert adapter.submit_call_count == 0
    assert repo.get_application_status(app_id) == ApplicationStatus.READY
    field_labels = [field["label"] for field in result.dry_run.transcript.payload["fields"]]
    assert "Will you now or in the future require sponsorship?" in field_labels


def test_greenhouse_dom_dry_run_hard_stop_goes_to_human_required(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=False)

    result = adapter.dry_run(
        page=_Page("<html><body><div class='cf-turnstile'></div>" + GREENHOUSE_FORM + "</body></html>"),
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
    )

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.dry_run is None
    assert adapter.submit_call_count == 0
    with repo.connect() as conn:
        task = conn.execute("SELECT category FROM human_tasks WHERE application_id = ?", (app_id,)).fetchone()
    assert task["category"] == "CAPTCHA"


def test_greenhouse_bad_pdf_never_reaches_submit_ready_upload_path(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    adapter = GreenhouseDryRunAdapter(repo, real_submission_enabled=False)

    result = adapter.dry_run(
        page=_Page(GREENHOUSE_FORM),
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc",
        resume_validation_status="PDF_QA_FAILED",
        persona="DATA",
    )

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.dry_run is not None
    assert result.dry_run.transcript.would_submit is False
    assert adapter.submit_call_count == 0
    resume_field = next(field for field in result.dry_run.resolutions if field.canonical_key == "application.resume")
    assert resume_field.status.value == "BLOCKED"
    assert resume_field.reason == "TRUTH_VALIDATION_FAILED"


def _seed_ready_with_resume(tmp_path):
    repo = JobAgentRepository(tmp_path / "gh.sqlite3")
    repo.initialize()
    job = Job(
        external_job_id="6087345002",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="SQL dashboards",
        source="greenhouse",
        source_url="https://boards.greenhouse.io/acme/jobs/6087345002",
        apply_url="https://boards.greenhouse.io/acme/jobs/6087345002",
        ats_type="greenhouse",
        job_family=JobFamily.DATA_ANALYTICS,
    )
    job_id = repo.upsert_job(job)
    job.id = job_id
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="greenhouse",
        ats_type="greenhouse",
        status=ApplicationStatus.READY,
    )
    app_id = repo.insert_application(app)
    artifact = ResumeArtifact(
        resume_id="resume-1",
        job_id=job_id,
        persona=Persona.DATA,
        base_version="test",
        generated_at="2026-09-07T00:00:00+00:00",
        changes={},
        validation_status="VALIDATED",
        file_path="data/resumes/resume-1.pdf",
        file_hash="sha256:abc",
    )
    repo.insert_resume_artifact(artifact)
    repo.attach_resume_to_application(app_id, artifact.resume_id)
    return repo, job, app_id


def _profile():
    return CandidateProfile(
        candidate_id="cand",
        schema_version=2,
        facts={
            "name.full": CandidateFact("name.full", "identity", "Jane Student", required=True),
            "contact.email": CandidateFact("contact.email", "contact", "jane@example.test", required=True),
            "contact.phone": CandidateFact("contact.phone", "contact", "+1 555 010 2222", required=True),
        },
        application_answers={"requires_sponsorship_now_or_future": "Yes"},
    )


class _Page:
    def __init__(self, html: str) -> None:
        self.html = html

    def content(self) -> str:
        return self.html

    def screenshot(self, *, path: str) -> None:
        return None
