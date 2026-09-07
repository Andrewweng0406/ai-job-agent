from app.applications.browser_capture import BrowserFieldCapture
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.services.browser_hard_stop import persist_browser_hard_stop


def test_browser_hard_stop_transitions_and_opens_task(tmp_path):
    repo, app_id, job_id = _seed_ready(tmp_path)
    capture = BrowserFieldCapture().capture(
        _Page("<html><body><div class='cf-turnstile'></div></body></html>"),
        ats_type="greenhouse",
        screenshot_path=tmp_path / "captcha.png",
    )

    assert persist_browser_hard_stop(repo, app_id, job_id, capture)
    assert repo.get_application_status(app_id) == ApplicationStatus.HUMAN_REQUIRED
    with repo.connect() as conn:
        task = conn.execute("SELECT category, context_json FROM human_tasks WHERE application_id = ?", (app_id,)).fetchone()
    assert task["category"] == "BOT_WALL"
    assert "captcha.png" in task["context_json"]


def test_email_verification_is_not_labeled_mfa(tmp_path):
    repo, app_id, job_id = _seed_ready(tmp_path)
    capture = BrowserFieldCapture().capture(
        _Page("<p>Please verify your email using the verification link we sent.</p>"),
        ats_type="lever",
    )

    persist_browser_hard_stop(repo, app_id, job_id, capture)

    with repo.connect() as conn:
        task = conn.execute("SELECT category FROM human_tasks WHERE application_id = ?", (app_id,)).fetchone()
    assert task["category"] == "EMAIL_VERIFICATION"


def _seed_ready(tmp_path):
    repo = JobAgentRepository(tmp_path / "hardstop.sqlite3")
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
    return repo, app_id, job_id


class _Page:
    def __init__(self, html: str) -> None:
        self.html = html

    def content(self) -> str:
        return self.html

    def screenshot(self, *, path: str) -> None:
        return None
