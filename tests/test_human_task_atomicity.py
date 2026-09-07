"""Human-task atomicity verification (WS1-C, HUMAN_QUEUE_DESIGN.md).

- application -> HUMAN_REQUIRED and human_task creation must be one atomic unit
  (no unexplained HUMAN_REQUIRED application).
- the same unresolved question encountered twice -> ONE idempotent task, not duplicates.
"""
from __future__ import annotations

import pytest

from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job

try:
    from app.applications.human_tasks import HumanTask
except Exception:  # pragma: no cover - module shape may differ
    HumanTask = None


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "ht.sqlite3")
    r.initialize()
    return r


def _app(repo) -> str:
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1", company_id="acme", company_name="Acme", title="Data Analyst",
            location="Remote", description="x", source="fixture", source_url="https://e.test/1",
            apply_url="https://e.test/apply/1", ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    a = Application(job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
                    job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    repo.insert_application(a)
    repo.transition_application(a.application_id, ApplicationStatus.ELIGIBLE, "seed")
    return a.application_id


def _mk_task(application_id, category="LEGAL_QUESTION", prompt="Describe your immigration status"):
    assert HumanTask is not None, "app.applications.human_tasks.HumanTask expected"
    kwargs = dict(application_id=application_id, category=category, prompt=prompt)
    try:
        return HumanTask(**kwargs)
    except TypeError:
        # fall back to whatever required fields exist
        return HumanTask(application_id=application_id, category=category, prompt=prompt, job_id=None,
                         status="OPEN", blocking_state=ApplicationStatus.ELIGIBLE.value)


@pytest.mark.skipif(HumanTask is None, reason="HumanTask model not present")
def test_mark_human_required_with_task_is_atomic(tmp_path):
    repo = _repo(tmp_path)
    app_id = _app(repo)
    repo.mark_human_required(app_id, "LEGAL_QUESTION", _mk_task(app_id))
    assert repo.get_application_status(app_id) == ApplicationStatus.HUMAN_REQUIRED
    with repo.connect() as conn:
        tasks = conn.execute(
            "SELECT COUNT(*) c FROM human_tasks WHERE application_id=? AND status IN ('OPEN','IN_PROGRESS')",
            (app_id,),
        ).fetchone()["c"]
    assert tasks == 1, "a HUMAN_REQUIRED application must have exactly one open task"


@pytest.mark.skipif(HumanTask is None, reason="HumanTask model not present")
def test_same_question_twice_is_one_task(tmp_path):
    repo = _repo(tmp_path)
    app_id = _app(repo)
    repo.mark_human_required(app_id, "LEGAL_QUESTION", _mk_task(app_id))
    # encountered again on a later attempt / retry
    repo.open_human_task(_mk_task(app_id))
    with repo.connect() as conn:
        tasks = conn.execute(
            "SELECT COUNT(*) c FROM human_tasks WHERE application_id=? AND category='LEGAL_QUESTION' "
            "AND status IN ('OPEN','IN_PROGRESS')",
            (app_id,),
        ).fetchone()["c"]
    assert tasks == 1, "duplicate unresolved question must not create a second open task"


def test_no_orphan_human_required_when_task_is_omitted(tmp_path):
    """If mark_human_required is called WITHOUT a task, that is an orphan (no explanation).

    Documents the expectation: workflow.py should always pass a task, or a follow-up must create one.
    """
    repo = _repo(tmp_path)
    app_id = _app(repo)
    repo.mark_human_required(app_id, "REAL_SUBMISSION_DISABLED")  # current workflow.py call shape
    with repo.connect() as conn:
        tasks = conn.execute(
            "SELECT COUNT(*) c FROM human_tasks WHERE application_id=?", (app_id,)
        ).fetchone()["c"]
    assert tasks >= 1
