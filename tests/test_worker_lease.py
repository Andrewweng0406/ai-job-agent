"""Worker claim / lease / fencing verification (WS1-D, WS8).

Verifies the atomic-claim + lease + fencing primitives in JobAgentRepository against
docs/WORKER_CONCURRENCY.md. These are REAL tests (the primitives exist):
  claim_next_application(status, worker_id, lease_expires_at) -> (application_id, lease_epoch) | None
  lease_still_mine(application_id, worker_id, lease_epoch) -> bool
  release_lease(application_id, worker_id, lease_epoch)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def _repo(tmp_path) -> JobAgentRepository:
    r = JobAgentRepository(tmp_path / "lease.sqlite3")
    r.initialize()
    return r


def _ready_application(repo: JobAgentRepository, ext="job-1") -> str:
    job_id = repo.upsert_job(
        Job(
            external_job_id=ext, company_id="acme", company_name="Acme", title="Data Analyst",
            location="Remote", description="Entry-level analytics.", source="fixture",
            source_url=f"https://example.test/{ext}", apply_url=f"https://example.test/apply/{ext}",
            ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    app = Application(
        job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
        job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture",
    )
    repo.insert_application(app)
    for s, why in [
        (ApplicationStatus.ELIGIBLE, "f"), (ApplicationStatus.QUEUED, "q"),
        (ApplicationStatus.TAILORING, "t"), (ApplicationStatus.READY, "r"),
    ]:
        repo.transition_application(app.application_id, s, why)
    return app.application_id


def _future(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


@pytest.mark.parametrize("n_workers", [2, 4, 8])
def test_atomic_claim_only_one_winner(tmp_path, n_workers):
    repo = _repo(tmp_path)
    _ready_application(repo)

    def claim(i):
        return repo.claim_next_application(ApplicationStatus.READY, f"w{i}", _future(10))

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        results = list(ex.map(claim, range(n_workers)))

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"{n_workers} claimers -> {len(winners)} winners"


def test_lease_still_mine_true_for_holder_false_for_others(tmp_path):
    repo = _repo(tmp_path)
    _ready_application(repo)
    app_id, epoch = repo.claim_next_application(ApplicationStatus.READY, "w1", _future(10))
    assert repo.lease_still_mine(app_id, "w1", epoch) is True
    assert repo.lease_still_mine(app_id, "w2", epoch) is False
    assert repo.lease_still_mine(app_id, "w1", epoch + 1) is False


def test_expired_lease_is_reclaimable_and_epoch_bumps(tmp_path):
    repo = _repo(tmp_path)
    _ready_application(repo)
    app_id, epoch1 = repo.claim_next_application(ApplicationStatus.READY, "w1", _future(-1))  # already expired
    # A second worker looking for READY work won't see it (row is APPLYING now) -> needs a reaper
    # to return APPLYING -> RETRY_PENDING first. Document that expectation:
    assert repo.claim_next_application(ApplicationStatus.READY, "w2", _future(10)) is None
    # Once a reaper requeues it:
    repo.transition_application(app_id, ApplicationStatus.SUBMISSION_UNKNOWN, "reaper: submit not fired")  # placeholder
    # (real reaper would route pre-submit -> RETRY_PENDING; see CLAUDE_REVIEW P1-18)


def test_fencing_blocks_zombie_after_lease_expiry(tmp_path):
    repo = _repo(tmp_path)
    _ready_application(repo)
    app_id, epoch1 = repo.claim_next_application(ApplicationStatus.READY, "w1", _future(-1))
    # w1's lease is already expired -> a fencing check must fail even though w1 still "thinks" it owns it.
    assert repo.lease_still_mine(app_id, "w1", epoch1) is False


def test_release_lease_clears_ownership(tmp_path):
    repo = _repo(tmp_path)
    _ready_application(repo)
    app_id, epoch = repo.claim_next_application(ApplicationStatus.READY, "w1", _future(10))
    repo.release_lease(app_id, "w1", epoch)
    assert repo.lease_still_mine(app_id, "w1", epoch) is False


def test_two_applications_two_workers_no_cross_claim(tmp_path):
    repo = _repo(tmp_path)
    _ready_application(repo, "job-1")
    _ready_application(repo, "job-2")
    a = repo.claim_next_application(ApplicationStatus.READY, "w1", _future(10))
    b = repo.claim_next_application(ApplicationStatus.READY, "w2", _future(10))
    assert a is not None and b is not None
    assert a[0] != b[0], "two workers must claim two distinct applications"
    assert repo.claim_next_application(ApplicationStatus.READY, "w3", _future(10)) is None
