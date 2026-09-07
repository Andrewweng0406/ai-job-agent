from app.applications.ashby_dry_run import AshbyDryRunAdapter
from app.applications.lever_dry_run import LeverDryRunAdapter
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import ResumeArtifact
from tests.test_greenhouse_dry_run import _Page, _profile


LEVER_FORM = """
<html><body>
  <form class="application-form">
    <div class="application-field"><label>Full name *</label><input name="name" required></div>
    <div class="application-field"><label>Email *</label><input name="email" required></div>
    <div class="application-field"><label>Phone *</label><input name="phone" required></div>
    <div class="application-field"><label>Resume/CV *</label><input name="resume" type="file" required></div>
    <fieldset>
      <legend>Will you now or in the future require sponsorship?</legend>
      <label>Yes<input type="radio" name="sponsorship" value="yes" required></label>
      <label>No<input type="radio" name="sponsorship" value="no"></label>
    </fieldset>
    <button type="submit">Submit application</button>
  </form>
</body></html>
"""


ASHBY_FORM = """
<html><body>
  <form data-testid="application-form">
    <div class="field"><div class="label">Full name *</div><input name="candidate[name]" required></div>
    <div class="field"><div class="label">Email *</div><input name="candidate[email]" required></div>
    <div class="field"><div class="label">Phone *</div><input name="candidate[phone]" required></div>
    <div class="field"><div class="label">Resume *</div><input name="resume" type="file" required></div>
    <div class="field">
      <label for="source">How did you hear about us?</label>
      <select id="source" name="source"><option>Company website</option><option>LinkedIn</option></select>
    </div>
    <button type="submit">Submit</button>
  </form>
</body></html>
"""


def test_lever_dom_dry_run_uses_common_no_submit_adapter(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path, "lever")
    adapter = LeverDryRunAdapter(repo, real_submission_enabled=False)

    result = adapter.dry_run(
        page=_Page(LEVER_FORM),
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
    assert result.dry_run.transcript.payload["job"]["ats"] == "lever"


def test_ashby_dom_dry_run_captures_custom_labels_and_stops_before_submit(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path, "ashby")
    adapter = AshbyDryRunAdapter(repo, real_submission_enabled=False)

    result = adapter.dry_run(
        page=_Page(ASHBY_FORM),
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
    assert [field["label"] for field in result.dry_run.transcript.payload["fields"]][:4] == [
        "Full name *",
        "Email *",
        "Phone *",
        "Resume *",
    ]


def test_ats_dom_dry_run_routes_empty_apply_page_to_ats_changed(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path, "lever")
    adapter = LeverDryRunAdapter(repo, real_submission_enabled=False)

    result = adapter.dry_run(
        page=_Page("<html><body><h1>Application unavailable</h1></body></html>"),
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
    )

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.reason == "ATS_CHANGED"
    assert adapter.submit_call_count == 0
    assert repo.get_application_status(app_id) == ApplicationStatus.HUMAN_REQUIRED


def _seed_ready_with_resume(tmp_path, ats_type: str):
    repo = JobAgentRepository(tmp_path / f"{ats_type}.sqlite3")
    repo.initialize()
    job = Job(
        external_job_id=f"{ats_type}-1",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="SQL dashboards",
        source=ats_type,
        source_url=f"https://jobs.example.test/{ats_type}/1",
        apply_url=f"https://jobs.example.test/{ats_type}/1",
        ats_type=ats_type,
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
        source=ats_type,
        ats_type=ats_type,
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
