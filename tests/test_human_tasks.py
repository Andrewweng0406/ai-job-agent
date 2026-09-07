from app.applications.human_tasks import HumanTask
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def test_open_human_task_is_idempotent_for_application_category(tmp_path):
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
        status=ApplicationStatus.HUMAN_REQUIRED,
    )
    app_id = repo.insert_application(app)

    first = repo.open_human_task(HumanTask(application_id=app_id, job_id=job_id, category="LEGAL_QUESTION", blocking_state="HUMAN_REQUIRED", prompt="Question 1"))
    second = repo.open_human_task(HumanTask(application_id=app_id, job_id=job_id, category="LEGAL_QUESTION", blocking_state="HUMAN_REQUIRED", prompt="Question 2"))

    with repo.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM human_tasks").fetchone()
        row = conn.execute("SELECT prompt FROM human_tasks WHERE task_id = ?", (first,)).fetchone()
    assert second == first
    assert count["count"] == 1
    assert row["prompt"] == "Question 2"

