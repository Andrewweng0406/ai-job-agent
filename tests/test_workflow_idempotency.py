"""Workflow idempotency verification (WS1-A, CLAUDE_REVIEW P1-13).

Verifies ApplicationWorkflowRunner.run() against the DB, not the in-memory object:
- refuses to run from non-runnable states
- DB state wins over a stale Application object
- two run() calls -> only one execution
- crash-after-submit -> no duplicate submit on restart
"""
from __future__ import annotations

import pytest

from app.applications.workflow import ApplicationWorkflowRunner
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "wf.sqlite3")
    r.initialize()
    return r


def _job(ext="job-1"):
    return Job(
        external_job_id=ext, company_id="acme", company_name="Acme", title="Data Analyst",
        location="Remote", description="Entry-level analytics.", source="fixture",
        source_url=f"https://example.test/{ext}", apply_url=f"https://example.test/apply/{ext}",
        ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS,
    )


def _seed(repo, status: ApplicationStatus) -> Application:
    job_id = repo.upsert_job(_job())
    app = Application(
        job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture",
    )
    repo.insert_application(app)
    path = [
        ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED, ApplicationStatus.TAILORING,
        ApplicationStatus.READY, ApplicationStatus.APPLYING, ApplicationStatus.SUBMITTED,
        ApplicationStatus.VERIFIED,
    ]
    for s in path:
        if repo.get_application_status(app.application_id) == status:
            break
        repo.transition_application(app.application_id, s, "seed")
    app.status = repo.get_application_status(app.application_id)
    return app


class _CountingAdapter:
    ats_type = "fixture"
    submits = 0

    def can_handle(self, job): return True
    def prepare(self, a): return a
    def fill(self, a): return a
    def upload_resume(self, a, p): return a
    def answer_questions(self, a): return a
    def validate(self, a): return a
    def submit(self, a):
        type(self).submits += 1
        return a
    def verify_submission(self, a):
        return True


@pytest.mark.parametrize(
    "status",
    [
        ApplicationStatus.APPLYING,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.SUBMISSION_UNKNOWN,
        ApplicationStatus.VERIFIED,
        ApplicationStatus.FAILED,
        ApplicationStatus.HUMAN_REQUIRED,
    ],
)
def test_run_rejects_non_runnable_states(tmp_path, status):
    repo = _repo(tmp_path)
    # build an app parked in `status`
    job_id = repo.upsert_job(_job())
    app = Application(job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
                      job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    repo.insert_application(app)
    for s in [ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED, ApplicationStatus.TAILORING,
              ApplicationStatus.READY, ApplicationStatus.APPLYING]:
        repo.transition_application(app.application_id, s, "seed")
        if repo.get_application_status(app.application_id) == status:
            break
    if status in {ApplicationStatus.SUBMITTED, ApplicationStatus.VERIFIED}:
        repo.transition_application(app.application_id, ApplicationStatus.SUBMITTED, "seed")
    if status == ApplicationStatus.VERIFIED:
        repo.transition_application(app.application_id, ApplicationStatus.VERIFIED, "seed")
    if status == ApplicationStatus.SUBMISSION_UNKNOWN:
        repo.transition_application(app.application_id, ApplicationStatus.SUBMISSION_UNKNOWN, "seed")
    if status == ApplicationStatus.FAILED:
        repo.transition_application(app.application_id, ApplicationStatus.FAILED, "seed")
    if status == ApplicationStatus.HUMAN_REQUIRED:
        repo.mark_human_required(app.application_id, "seed")

    assert repo.get_application_status(app.application_id) == status
    adapter = _CountingAdapter(); type(adapter).submits = 0
    runner = ApplicationWorkflowRunner([adapter], real_submission_enabled=True)
    stale = Application(job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
                       job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    stale.application_id = app.application_id
    stale.status = ApplicationStatus.READY  # stale in-memory claims READY
    result = runner.run(stale, _job(), resume_path="/tmp/r.pdf", repository=repo)
    assert result.reason and result.reason.startswith("APPLICATION_NOT_READY"), result
    assert adapter.submits == 0, "must not submit from a non-runnable DB state"


def test_db_state_wins_over_stale_object(tmp_path):
    repo = _repo(tmp_path)
    app = _seed(repo, ApplicationStatus.SUBMITTED)
    adapter = _CountingAdapter(); type(adapter).submits = 0
    runner = ApplicationWorkflowRunner([adapter], real_submission_enabled=True)
    stale = Application(job_id=app.job_id, company="Acme", position="Data Analyst", location="Remote",
                        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    stale.application_id = app.application_id
    stale.status = ApplicationStatus.READY
    result = runner.run(stale, _job(), resume_path="/tmp/r.pdf", repository=repo)
    assert adapter.submits == 0
    assert repo.get_application_status(app.application_id) == ApplicationStatus.SUBMITTED


def test_second_run_call_does_not_re_execute(tmp_path):
    repo = _repo(tmp_path)
    app = _seed(repo, ApplicationStatus.READY)
    adapter = _CountingAdapter(); type(adapter).submits = 0
    runner = ApplicationWorkflowRunner([adapter], real_submission_enabled=True)

    r1 = runner.run(app, _job(), resume_path="/tmp/r.pdf", repository=repo)
    status_after_1 = repo.get_application_status(app.application_id)
    r2 = runner.run(app, _job(), resume_path="/tmp/r.pdf", repository=repo)

    assert adapter.submits == 1, "submit must run exactly once across two run() calls"
    assert r2.reason and r2.reason.startswith("APPLICATION_NOT_READY")
    assert status_after_1 in {ApplicationStatus.VERIFIED, ApplicationStatus.SUBMITTED}


def test_crash_after_submit_no_duplicate_on_restart(tmp_path):
    repo = _repo(tmp_path)
    app = _seed(repo, ApplicationStatus.READY)

    class _CrashAfterSubmit(_CountingAdapter):
        def verify_submission(self, a):
            raise TimeoutError("network dropped after submit POST")

    adapter = _CrashAfterSubmit(); type(adapter).submits = 0
    runner = ApplicationWorkflowRunner([adapter], real_submission_enabled=True)
    result = runner.run(app, _job(), resume_path="/tmp/r.pdf", repository=repo)
    assert result.status == ApplicationStatus.SUBMISSION_UNKNOWN
    assert adapter.submits == 1

    # "restart": a fresh runner tries the same application again
    adapter2 = _CountingAdapter(); type(adapter2).submits = 0
    runner2 = ApplicationWorkflowRunner([adapter2], real_submission_enabled=True)
    fresh = Application(job_id=app.job_id, company="Acme", position="Data Analyst", location="Remote",
                        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    fresh.application_id = app.application_id
    fresh.status = ApplicationStatus.READY
    r2 = runner2.run(fresh, _job(), resume_path="/tmp/r.pdf", repository=repo)
    assert adapter2.submits == 0, "SUBMISSION_UNKNOWN must never be re-driven through the form"
    assert r2.reason and r2.reason.startswith("APPLICATION_NOT_READY")
