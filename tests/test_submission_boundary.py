"""P1-24 submission-boundary re-verification (Round 3.1 §2).

Invariant: ANY application that may have crossed the submission boundary must NEVER automatically
return to a state that permits a blind submission retry.

The durable signal is now `applications.submit_attempted_at` (not a substring in `notes`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.applications.state_machine import ALLOWED_TRANSITIONS
from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "b.sqlite3")
    r.initialize()
    return r


def _claimed_applying(repo, ext="j1"):
    job = Job(external_job_id=ext, company_id="acme", company_name="Acme", title="Data Analyst",
              location="Remote", description="x", source="fixture", source_url=f"https://e/{ext}",
              apply_url=f"https://e/apply/{ext}", ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS)
    job.id = repo.upsert_job(job)
    app = Application(job_id=job.id, company="Acme", position="Data Analyst", location="Remote",
                     job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    app_id = repo.insert_application(app)
    for s in [ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED, ApplicationStatus.TAILORING, ApplicationStatus.READY]:
        repo.transition_application(app_id, s, "seed")
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    repo.claim_next_application(ApplicationStatus.READY, "w1", past)  # -> APPLYING, lease already expired
    return app_id


def test_boundary_crossed_reaps_to_submission_unknown(tmp_path):
    repo = _repo(tmp_path)
    app_id = _claimed_applying(repo)
    repo.mark_submit_attempted(app_id)  # the worker recorded "about to click submit"
    reaped = repo.reap_expired_leases()
    assert (app_id, ApplicationStatus.SUBMISSION_UNKNOWN) in reaped
    assert repo.get_application_status(app_id) == ApplicationStatus.SUBMISSION_UNKNOWN


def test_boundary_not_crossed_reaps_to_retry_pending(tmp_path):
    repo = _repo(tmp_path)
    app_id = _claimed_applying(repo)
    # no mark_submit_attempted -> crash happened before the boundary
    reaped = repo.reap_expired_leases()
    assert (app_id, ApplicationStatus.RETRY_PENDING) in reaped
    assert repo.get_application_status(app_id) == ApplicationStatus.RETRY_PENDING


def test_submission_unknown_can_never_reach_a_submit_permitting_state():
    seen = {ApplicationStatus.SUBMISSION_UNKNOWN}
    stack = [ApplicationStatus.SUBMISSION_UNKNOWN]
    while stack:
        cur = stack.pop()
        for nxt in ALLOWED_TRANSITIONS[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    forbidden = {ApplicationStatus.APPLYING, ApplicationStatus.RETRY_PENDING, ApplicationStatus.READY} & seen
    assert not forbidden, f"SUBMISSION_UNKNOWN can reach {sorted(s.value for s in forbidden)}"


def test_stale_submit_attempted_on_a_reREADY_row_is_guarded(tmp_path):
    repo = _repo(tmp_path)
    app_id = _claimed_applying(repo)
    repo.mark_submit_attempted(app_id)
    repo.reap_expired_leases()  # -> SUBMISSION_UNKNOWN
    # a human resolves it as a genuine non-submit and pushes it back toward the queue
    repo.transition_application(app_id, ApplicationStatus.SKIPPED, "human: was not actually submitted")
    # (there is no path back to READY today; if one is ever added, submit_attempted_at must be cleared
    #  or the claim must refuse it). Assert the column is clear if the row is ever claimable again.
    with repo.connect() as conn:
        val = conn.execute("SELECT submit_attempted_at FROM applications WHERE application_id=?", (app_id,)).fetchone()[0]
    assert val is None, "submit_attempted_at must be cleared before an application can be re-claimed for submission"
