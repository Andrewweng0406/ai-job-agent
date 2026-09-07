"""Adversarial tests for ApplicationWorkflowRunner persistence + idempotency (CLAUDE_REVIEW P1-13).

The runner currently mutates `application.status` in memory only. These tests encode the required
behavior: the workflow must persist through the repository and must refuse to re-drive a form for an
application that already reached a submit/terminal state.

xfail(strict=False) -> promote to plain asserts once P1-13 is implemented.
"""
from __future__ import annotations

import pytest

from app.applications.workflow import ApplicationWorkflowRunner
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def _job() -> Job:
    return Job(
        external_job_id="job-1", company_id="acme", company_name="Acme", title="Data Analyst",
        location="Remote", description="Entry-level analytics.", source="fixture",
        source_url="https://example.test/job-1", apply_url="https://example.test/apply/job-1",
        ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS,
    )


class _AdapterSubmitsOnce:
    ats_type = "fixture"
    calls = 0

    def can_handle(self, job): return True
    def prepare(self, a): return a
    def fill(self, a): return a
    def upload_resume(self, a, p): return a
    def answer_questions(self, a): return a
    def validate(self, a): return a

    def submit(self, a):
        type(self).calls += 1
        return a

    def verify_submission(self, a):
        return True


def _mk_app(job_id: int) -> Application:
    return Application(
        job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture",
    )


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-13: workflow runner does not persist via the repository")
def test_workflow_persists_status_transitions(tmp_path):
    repo = JobAgentRepository(tmp_path / "a.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(_job())
    app = _mk_app(job_id)
    repo.insert_application(app)
    for s, why in [
        (ApplicationStatus.ELIGIBLE, "f"), (ApplicationStatus.QUEUED, "q"),
        (ApplicationStatus.TAILORING, "t"), (ApplicationStatus.READY, "r"),
    ]:
        repo.transition_application(app.application_id, s, why)

    runner = ApplicationWorkflowRunner([_AdapterSubmitsOnce()], real_submission_enabled=True)
    runner.run(app, _job(), resume_path="/tmp/r.pdf", repository=repo)  # type: ignore[call-arg]

    with repo.connect() as conn:
        row = conn.execute("SELECT status FROM applications WHERE application_id=?", (app.application_id,)).fetchone()
        n = conn.execute(
            "SELECT COUNT(*) c FROM application_state_transitions WHERE application_id=? AND to_status='VERIFIED'",
            (app.application_id,),
        ).fetchone()["c"]
    assert row["status"] == "VERIFIED"
    assert n == 1, "workflow must log the VERIFIED transition"


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-13: workflow re-drives the form for an already-submitted application")
def test_workflow_refuses_to_resubmit_already_submitted(tmp_path):
    adapter = _AdapterSubmitsOnce()
    runner = ApplicationWorkflowRunner([adapter], real_submission_enabled=True)
    app = _mk_app(1)
    app.status = ApplicationStatus.SUBMITTED  # already submitted in a prior run
    runner.run(app, _job(), resume_path="/tmp/r.pdf")
    assert adapter.calls == 0, "must not call submit() again for an application past APPLYING"
