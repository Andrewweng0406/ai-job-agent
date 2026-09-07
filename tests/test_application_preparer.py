import json

from app.applications.queue import ApplicationQueue
from app.database.repository import JobAgentRepository
from app.llm.tailoring import TailoringMode
from app.llm.fact_selection import FactSelectionResult
from app.llm.router import LLMUsage
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.resumes.profile import CandidateFact, CandidateProfile
from app.services.application_preparer import ApplicationPreparer


def test_prepare_next_generates_pdf_and_preview(tmp_path):
    repo, app_id = _seed_eligible(tmp_path)
    ApplicationQueue(repo).enqueue_eligible()
    profile = _complete_profile()

    result = ApplicationPreparer(repo, resume_generator=None).prepare_next(profile, TailoringMode.FAST)

    assert result.status == ApplicationStatus.READY
    assert result.preview is not None
    assert result.preview.resume_used.endswith(".pdf")
    with repo.connect() as conn:
        app = conn.execute("SELECT status, resume_id FROM applications WHERE application_id = ?", (app_id,)).fetchone()
        resumes = conn.execute("SELECT COUNT(*) AS count FROM resumes").fetchone()
    assert app["status"] == "READY"
    assert app["resume_id"]
    assert resumes["count"] == 1


def test_prepare_next_profile_incomplete_opens_human_task(tmp_path):
    repo, app_id = _seed_eligible(tmp_path)
    ApplicationQueue(repo).enqueue_eligible()
    profile = CandidateProfile(
        candidate_id="cand",
        schema_version=2,
        facts={"name.full": CandidateFact("name.full", "identity", "TODO", required=True)},
        application_answers={},
    )

    result = ApplicationPreparer(repo).prepare_next(profile)

    assert result.status == ApplicationStatus.HUMAN_REQUIRED
    with repo.connect() as conn:
        app = conn.execute("SELECT status, human_required_reason FROM applications WHERE application_id = ?", (app_id,)).fetchone()
        tasks = conn.execute("SELECT COUNT(*) AS count FROM human_tasks").fetchone()
    assert app["status"] == "HUMAN_REQUIRED"
    assert app["human_required_reason"] == "PROFILE_INCOMPLETE"
    assert tasks["count"] == 1


def test_prepare_next_records_safe_llm_selection_metadata(tmp_path):
    class Selector:
        def select(self, **kwargs):
            assert kwargs["stage0_passed"] is True
            return FactSelectionResult(
                ["skill.sql"],
                LLMUsage("3", "gpt-5-mini", 80, 20, 4, 0.000013, False),
            )

    repo, _ = _seed_eligible(tmp_path)
    ApplicationQueue(repo).enqueue_eligible()
    result = ApplicationPreparer(repo, fact_selector=Selector()).prepare_next(
        _complete_profile(), TailoringMode.FAST
    )

    assert result.status == ApplicationStatus.READY
    with repo.connect() as conn:
        row = conn.execute("SELECT changes_json FROM resumes").fetchone()
    changes = json.loads(row["changes_json"])
    assert changes["selected_fact_ids"] == ["skill.sql"]
    assert changes["selection"]["source"] == "llm_fact_selection"
    assert changes["selection"]["usage"]["model"] == "gpt-5-mini"
    assert "prompt" not in json.dumps(changes).lower()


def _seed_eligible(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
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
        status=ApplicationStatus.ELIGIBLE,
    )
    app_id = repo.insert_application(app)
    return repo, app_id


def _complete_profile():
    return CandidateProfile(
        candidate_id="cand",
        schema_version=2,
        facts={
            "name.full": CandidateFact("name.full", "identity", "Jane Student", required=True),
            "edu.primary.school": CandidateFact("edu.primary.school", "education", "San Jose State University", required=True),
            "edu.primary.degree": CandidateFact("edu.primary.degree", "education", "B.S. Business Analytics", required=True),
            "edu.primary.grad_date": CandidateFact("edu.primary.grad_date", "education", "May 2026", required=True),
            "skill.sql": CandidateFact("skill.sql", "skill", "SQL"),
            "project.dashboard": CandidateFact("project.dashboard", "project", "Built dashboards using SQL."),
        },
        application_answers={"work_authorized_us": "Yes"},
    )
