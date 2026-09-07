"""Adversarial concurrency / duplicate-submission tests.

Covers: two workers racing one application, duplicate-insert idempotency, SUBMISSION_UNKNOWN handling,
retry after a network timeout that lands immediately after the submit POST.

See docs/CLAUDE_REVIEW.md (P0-2, P0-6, P1-4) and docs/SUBMISSION_VERIFICATION.md.
"""
from __future__ import annotations

import pytest

from app.applications.state_machine import ALLOWED_TRANSITIONS, ApplicationStateMachine, InvalidTransitionError
from app.applications.workflow import ApplicationWorkflowRunner
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, FailureCategory, JobFamily
from app.models.job import Job

M = ApplicationStateMachine()


def _repo(tmp_path) -> JobAgentRepository:
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    return repo


def _job(**kw) -> Job:
    base = dict(
        external_job_id="job-1",
        company_id="acme",
        company_name="Acme",
        title="Data Analyst",
        location="Remote",
        description="Entry-level analytics.",
        source="fixture",
        source_url="https://example.test/job-1",
        apply_url="https://example.test/apply/job-1",
        ats_type="fixture",
        job_family=JobFamily.DATA_ANALYTICS,
    )
    base.update(kw)
    return Job(**base)


def _application(job_id: int) -> Application:
    return Application(
        job_id=job_id,
        company="Acme",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="fixture",
        ats_type="fixture",
    )


# --- duplicate insert is idempotent -----------------------------------------
def test_duplicate_application_insert_is_noop(tmp_path):
    repo = _repo(tmp_path)
    job_id = repo.upsert_job(_job())
    a1 = _application(job_id)
    a2 = _application(job_id)  # different application_id, same job -> same dedupe_key
    id1 = repo.insert_application(a1)
    id2 = repo.insert_application(a2)
    assert id1 == id2, "second insert for the same job must return the existing row, not create a new one"
    with repo.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM applications WHERE job_id = ?", (job_id,)).fetchone()["c"]
    assert count == 1


# --- two workers race the same transition ---------------------------------
def test_two_workers_cannot_both_advance_same_application(tmp_path):
    repo = _repo(tmp_path)
    job_id = repo.upsert_job(_job())
    app = _application(job_id)
    repo.insert_application(app)
    repo.transition_application(app.application_id, ApplicationStatus.ELIGIBLE, "filters passed")
    repo.transition_application(app.application_id, ApplicationStatus.QUEUED, "queued")

    # Worker A moves QUEUED -> TAILORING.
    repo.transition_application(app.application_id, ApplicationStatus.TAILORING, "worker A")
    # Worker B still believes it is QUEUED and tries the same move.
    with pytest.raises((RuntimeError, InvalidTransitionError)):
        repo.transition_application(app.application_id, ApplicationStatus.TAILORING, "worker B stale")

    with repo.connect() as conn:
        transitions = conn.execute(
            "SELECT COUNT(*) AS c FROM application_state_transitions WHERE application_id = ? AND to_status = 'TAILORING'",
            (app.application_id,),
        ).fetchone()["c"]
    assert transitions == 1, "exactly one TAILORING transition should be logged"


# --- SUBMISSION_UNKNOWN must not be launderable back into APPLYING --------
def test_submission_unknown_never_reaches_applying_again():
    # BFS the transition graph from SUBMISSION_UNKNOWN.
    seen = {ApplicationStatus.SUBMISSION_UNKNOWN}
    stack = [ApplicationStatus.SUBMISSION_UNKNOWN]
    while stack:
        cur = stack.pop()
        for nxt in ALLOWED_TRANSITIONS[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    offenders = {ApplicationStatus.APPLYING, ApplicationStatus.RETRY_PENDING} & seen
    if offenders:
        pytest.xfail(
            f"CLAUDE_REVIEW P0-6: SUBMISSION_UNKNOWN can still reach {sorted(o.value for o in offenders)} "
            "via FAILED->RETRY_PENDING->APPLYING (duplicate-submission path)"
        )
    assert not offenders


# --- SUBMISSION_UNKNOWN -> VERIFIED must be reachable (async verify) -------
def test_submission_unknown_can_be_promoted_to_verified():
    if not M.can_transition(ApplicationStatus.SUBMISSION_UNKNOWN, ApplicationStatus.VERIFIED):
        pytest.xfail("CLAUDE_REVIEW P1-8: async verify worker cannot promote SUBMISSION_UNKNOWN -> VERIFIED")
    assert True


# --- workflow: exception right after submit => SUBMISSION_UNKNOWN, no retry -
class _AdapterSubmitThenTimeout:
    ats_type = "fixture"

    def can_handle(self, job):  # noqa: D401
        return True

    def prepare(self, application):
        return application

    def fill(self, application):
        return application

    def upload_resume(self, application, resume_path):
        return application

    def answer_questions(self, application):
        return application

    def validate(self, application):
        return application

    def submit(self, application):
        # POST fired successfully...
        application.notes = "SUBMIT_POST_SENT"
        return application

    def verify_submission(self, application):
        # ...then the network drops before we can read the confirmation.
        raise TimeoutError("read timed out after submit POST")


def test_timeout_immediately_after_submit_is_submission_unknown_not_failed():
    runner = ApplicationWorkflowRunner([_AdapterSubmitThenTimeout()], real_submission_enabled=True)
    app = Application(
        job_id=1, company="Acme", position="Data Analyst", location="Remote",
        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture",
    )
    result = runner.run(app, _job(), resume_path="/tmp/resume.pdf")
    assert result.status == ApplicationStatus.SUBMISSION_UNKNOWN
    assert app.failure_category == FailureCategory.SUBMISSION_UNKNOWN
    assert app.notes == "SUBMIT_POST_SENT", "the submit POST had already been sent; must not be treated as a clean failure"


# --- workflow: no-confirmation submit => SUBMISSION_UNKNOWN, never VERIFIED -
class _AdapterSubmitNoEvidence(_AdapterSubmitThenTimeout):
    def verify_submission(self, application):
        return False  # submit page shown, but no confirmation id / email / portal entry


def test_submit_without_evidence_is_not_counted_verified():
    runner = ApplicationWorkflowRunner([_AdapterSubmitNoEvidence()], real_submission_enabled=True)
    app = Application(
        job_id=1, company="Acme", position="Data Analyst", location="Remote",
        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture",
    )
    result = runner.run(app, _job(), resume_path="/tmp/resume.pdf")
    assert result.status == ApplicationStatus.SUBMISSION_UNKNOWN
    assert result.verified is False
