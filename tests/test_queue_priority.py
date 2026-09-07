from pathlib import Path

from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def test_queue_candidates_prioritize_known_persona_families(tmp_path: Path):
    repo = JobAgentRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    for index, family in enumerate((JobFamily.UNKNOWN, JobFamily.DATA_ANALYTICS), start=1):
        job = Job(str(index), "c", "C", f"Role {index}", "Remote", "entry level",
                  "fixture", f"https://x/{index}", f"https://x/{index}", "fixture", job_family=family)
        job.id = repo.upsert_job(job)
        app = Application(job_id=job.id, company="C", position=job.title, location="Remote",
                          job_family=family, source="fixture", ats_type="fixture")
        repo.insert_application(app)
        repo.transition_application(app.application_id, ApplicationStatus.ELIGIBLE, "test")
    rows = repo.get_applications_by_status(ApplicationStatus.ELIGIBLE, 1)
    assert rows[0]["job_family"] == JobFamily.DATA_ANALYTICS.value
