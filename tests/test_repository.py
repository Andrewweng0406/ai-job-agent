from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def test_repository_initializes_and_logs_state_transition(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Business Analyst",
            location="Chicago, IL",
            description="Entry-level business analyst.",
            source="fixture",
            source_url="https://example.test/job-1",
            apply_url="https://example.test/apply/job-1",
            ats_type="fixture",
            job_family=JobFamily.BUSINESS_SYSTEMS,
        )
    )
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Business Analyst",
        location="Chicago, IL",
        job_family=JobFamily.BUSINESS_SYSTEMS,
        source="fixture",
        ats_type="fixture",
    )
    repo.insert_application(app)
    repo.transition_application(app.application_id, ApplicationStatus.ELIGIBLE, "passed filters")

    with repo.connect() as conn:
        row = conn.execute("SELECT status FROM applications WHERE application_id = ?", (app.application_id,)).fetchone()
        transitions = conn.execute("SELECT COUNT(*) AS count FROM application_state_transitions").fetchone()
    assert row["status"] == "ELIGIBLE"
    assert transitions["count"] == 1

