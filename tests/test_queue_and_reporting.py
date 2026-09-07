from datetime import date

from app.applications.queue import ApplicationQueue
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.reporting.daily_report import build_daily_report


def test_queue_assigns_persona_and_transitions(tmp_path):
    repo, app_id = _seed_application(tmp_path)

    result = ApplicationQueue(repo).enqueue_eligible(limit=10)

    assert result.queued == 1
    with repo.connect() as conn:
        row = conn.execute("SELECT status, persona FROM applications WHERE application_id = ?", (app_id,)).fetchone()
        transitions = conn.execute("SELECT COUNT(*) AS count FROM application_state_transitions").fetchone()
    assert row["status"] == "QUEUED"
    assert row["persona"] == "DATA"
    assert transitions["count"] == 1


def test_daily_report_counts_core_metrics(tmp_path):
    repo, _app_id = _seed_application(tmp_path)
    report = build_daily_report(repo, date.today(), target_submissions=100)

    assert report.target_submissions == 100
    assert report.eligible_jobs == 1
    assert report.by_status["ELIGIBLE"] == 1


def _seed_application(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="Entry-level SQL role.",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
            job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    repo.record_job_filter_result(job_id, True, None)
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="fixture",
        ats_type="fixture",
        status=ApplicationStatus.ELIGIBLE,
    )
    repo.insert_application(app)
    return repo, app.application_id

