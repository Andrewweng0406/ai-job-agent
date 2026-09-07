from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.tracking.verification import EvidenceTier, VerificationEvidence, VerificationService


def test_strong_evidence_promotes_submitted_to_verified(tmp_path):
    repo, app_id = _seed_app(tmp_path, ApplicationStatus.SUBMITTED)

    status = VerificationService(repo).record_evidence(
        app_id,
        VerificationEvidence(
            tier=EvidenceTier.T1_CONFIRMATION_ID,
            source="success_page",
            confirmation_id="R-123",
        ),
    )

    with repo.connect() as conn:
        row = conn.execute(
            "SELECT status, submission_verified_at, confirmation_data_json FROM applications WHERE application_id = ?",
            (app_id,),
        ).fetchone()
    assert status == ApplicationStatus.VERIFIED
    assert row["status"] == "VERIFIED"
    assert row["submission_verified_at"]
    assert '"confirmation_id": "R-123"' in row["confirmation_data_json"]


def test_weak_page_text_does_not_verify_by_itself(tmp_path):
    repo, app_id = _seed_app(tmp_path, ApplicationStatus.SUBMITTED)

    status = VerificationService(repo).record_evidence(
        app_id,
        VerificationEvidence(
            tier=EvidenceTier.T5_WEAK_PAGE_TEXT,
            source="success_page",
            success_page_text_match="Thank you for applying",
        ),
    )

    assert status == ApplicationStatus.SUBMITTED
    assert repo.get_application_status(app_id) == ApplicationStatus.SUBMITTED


def test_unknown_submission_can_be_verified_with_late_email(tmp_path):
    repo, app_id = _seed_app(tmp_path, ApplicationStatus.SUBMISSION_UNKNOWN)

    status = VerificationService(repo).record_evidence(
        app_id,
        VerificationEvidence(
            tier=EvidenceTier.T3_CONFIRMATION_EMAIL,
            source="mailbox",
            email_message_id="<message@example.test>",
        ),
    )

    assert status == ApplicationStatus.VERIFIED


def _seed_app(tmp_path, status: ApplicationStatus):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="SQL",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
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
        ats_type="fixture",
        status=status,
    )
    app_id = repo.insert_application(app)
    return repo, app_id

