from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import ResumeArtifact
from app.resumes.profile import CandidateFact, CandidateProfile
from app.services.dry_run_preparer import ApplicationDryRunPreparer, HtmlAtsFieldProvider


def test_dry_run_next_persists_transcript_for_ready_application(tmp_path):
    repo, app_id = _seed_ready(tmp_path, with_resume=True)
    result = ApplicationDryRunPreparer(repo).dry_run_next(_complete_profile())

    assert result.status == ApplicationStatus.READY
    assert result.dry_run is not None
    assert result.dry_run.transcript.would_submit
    assert repo.get_application_status(app_id) == ApplicationStatus.READY
    with repo.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM dry_run_transcripts WHERE application_id = ?", (app_id,)).fetchone()
    assert row["count"] == 1


def test_dry_run_next_missing_resume_opens_human_task(tmp_path):
    repo, app_id = _seed_ready(tmp_path, with_resume=False)
    result = ApplicationDryRunPreparer(repo).dry_run_next(_complete_profile())

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    assert result.reason == "RESUME_ARTIFACT_MISSING"
    assert repo.get_application_status(app_id) == ApplicationStatus.HUMAN_REQUIRED
    with repo.connect() as conn:
        task = conn.execute("SELECT category FROM human_tasks WHERE application_id = ?", (app_id,)).fetchone()
    assert task["category"] == "RESUME_ARTIFACT_MISSING"


def test_dry_run_next_can_use_extracted_html_fields(tmp_path):
    repo, app_id = _seed_ready(tmp_path, with_resume=True)
    provider = HtmlAtsFieldProvider(
        {
            "greenhouse": """
            <form id="application_form">
              <label for="email">Email</label><input id="email" required />
              <label for="resume">Resume</label><input id="resume" type="file" required />
            </form>
            """
        }
    )

    result = ApplicationDryRunPreparer(repo, field_provider=provider).dry_run_next(_complete_profile())

    assert result.status == ApplicationStatus.READY
    assert result.dry_run is not None
    assert result.dry_run.transcript.would_submit
    labels = [field["label"] for field in result.dry_run.transcript.payload["fields"]]
    assert labels == ["Email", "Resume"]
    assert repo.get_application_status(app_id) == ApplicationStatus.READY


def _seed_ready(tmp_path, with_resume: bool):
    repo = JobAgentRepository(tmp_path / "dry.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="SQL dashboards",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="greenhouse",
            job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="fixture",
        ats_type="greenhouse",
        status=ApplicationStatus.READY,
    )
    app_id = repo.insert_application(app)
    if with_resume:
        artifact = ResumeArtifact(
            resume_id="resume-1",
            job_id=job_id,
            persona=Persona.DATA,
            base_version="test",
            generated_at="2026-09-07T00:00:00+00:00",
            changes={},
            validation_status="VALIDATED",
            file_path="data/resumes/resume-1.pdf",
            file_hash="abc123",
        )
        repo.insert_resume_artifact(artifact)
        repo.attach_resume_to_application(app_id, artifact.resume_id)
    return repo, app_id


def _complete_profile():
    return CandidateProfile(
        candidate_id="cand",
        schema_version=2,
        facts={
            "name.full": CandidateFact("name.full", "identity", "Jane Student", required=True),
            "contact.email": CandidateFact("contact.email", "contact", "jane@example.test", required=True),
            "contact.phone": CandidateFact("contact.phone", "contact", "+1 555 010 2222", required=True),
            "links.linkedin": CandidateFact("links.linkedin", "link", "https://linkedin.example/jane"),
            "links.github": CandidateFact("links.github", "link", "https://github.example/jane"),
        },
        application_answers={
            "work_authorized_us": "Yes",
            "requires_sponsorship_now_or_future": "Yes",
        },
    )
