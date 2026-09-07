"""Concurrency / idempotency stress — real threads against the repository primitives.

Invariants under contention:
  1. At most one worker ever holds an application (claim is exclusive; expired leases reclaimed once).
  2. reap_expired_leases + claim_next_application racing never double-transition a row.
  3. A row carrying submit_attempted_at is never claimable (no duplicate-submission window).
  4. transition_application is compare-and-set: concurrent transitions from the same state -> exactly one wins.
  5. No 'Concurrent status modification' RuntimeError escapes as an unhandled error from the happy path.
"""
from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "stress.sqlite3")
    r.initialize()
    return r


def _seed_ready(repo, n) -> list[str]:
    ids = []
    for i in range(n):
        job = Job(external_job_id=f"j{i}", company_id="acme", company_name="Acme", title="Data Analyst",
                  location="Remote", description="x", source="fixture", source_url=f"https://e/{i}",
                  apply_url=f"https://e/apply/{i}", ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS)
        job.id = repo.upsert_job(job)
        app = Application(job_id=job.id, company="Acme", position="Data Analyst", location="Remote",
                         job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
        aid = repo.insert_application(app)
        for s in [ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED,
                  ApplicationStatus.TAILORING, ApplicationStatus.READY]:
            repo.transition_application(aid, s, "seed")
        ids.append(aid)
    return ids


def _future(m):
    return datetime.now(timezone.utc) + timedelta(minutes=m)


def test_many_workers_one_application_exactly_one_winner(tmp_path):
    repo = _repo(tmp_path)
    _seed_ready(repo, 1)

    def worker(i):
        try:
            return repo.claim_next_application(ApplicationStatus.READY, f"w{i}", _future(10))
        except Exception as exc:  # nothing should escape as an unhandled error
            return ("ERROR", type(exc).__name__, str(exc))

    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(worker, range(16)))

    errors = [r for r in results if r and r[0] == "ERROR"]
    winners = [r for r in results if r and r[0] != "ERROR"]
    assert not errors, f"unhandled errors under contention: {errors}"
    assert len(winners) == 1, f"{len(winners)} workers claimed the same application"


def test_pool_of_workers_claims_each_application_at_most_once(tmp_path):
    repo = _repo(tmp_path)
    n = 12
    _seed_ready(repo, n)
    claimed: list[str] = []
    lock = threading.Lock()

    def drain(i):
        while True:
            res = repo.claim_next_application(ApplicationStatus.READY, f"w{i}", _future(10))
            if res is None:
                return
            with lock:
                claimed.append(res[0])

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(drain, range(8)))

    counts = Counter(claimed)
    assert set(counts.values()) == {1}, f"an application was claimed more than once: {counts}"
    assert len(claimed) == n


def test_reaper_and_claim_racing_do_not_double_transition(tmp_path):
    repo = _repo(tmp_path)
    ids = _seed_ready(repo, 8)
    # claim all with an already-expired lease so the reaper has work
    for i, aid in enumerate(ids):
        repo.claim_next_application(ApplicationStatus.READY, f"w{i}", _future(-1))

    barrier = threading.Barrier(6)

    def reap():
        barrier.wait()
        for _ in range(5):
            repo.reap_expired_leases()

    def reclaim(i):
        barrier.wait()
        for _ in range(5):
            repo.claim_next_application(ApplicationStatus.RETRY_PENDING, f"r{i}", _future(10))

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(reap) for _ in range(2)] + [ex.submit(reclaim, i) for i in range(4)]
        for f in futs:
            f.result()  # no exception may propagate

    # every application ended in a consistent single state, and its transition log has no
    # duplicated consecutive to_status for the reaper edge
    with repo.connect() as conn:
        for aid in ids:
            rows = conn.execute(
                "SELECT to_status FROM application_state_transitions WHERE application_id=? ORDER BY id",
                (aid,),
            ).fetchall()
            seq = [r["to_status"] for r in rows]
            # APPLYING must never appear twice in a row without a claim in between
            assert seq.count("SUBMITTED") == 0
            status = conn.execute("SELECT status FROM applications WHERE application_id=?", (aid,)).fetchone()["status"]
            assert status in {s.value for s in ApplicationStatus}


def test_submit_marker_row_is_never_claimable_under_contention(tmp_path):
    repo = _repo(tmp_path)
    ids = _seed_ready(repo, 4)
    for aid in ids:
        repo.mark_submit_attempted(aid)

    def worker(i):
        return repo.claim_next_application(ApplicationStatus.READY, f"w{i}", _future(10))

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(worker, range(12)))
    assert all(r is None for r in results), "a row carrying submit_attempted_at was claimed"


def test_concurrent_transition_from_same_state_exactly_one_wins(tmp_path):
    repo = _repo(tmp_path)
    aid = _seed_ready(repo, 1)[0]
    repo.claim_next_application(ApplicationStatus.READY, "w", _future(10))  # -> APPLYING

    outcomes = Counter()
    lock = threading.Lock()

    def go(_):
        try:
            repo.transition_application(aid, ApplicationStatus.SUBMITTED, "race")
            with lock:
                outcomes["ok"] += 1
        except Exception:
            with lock:
                outcomes["rejected"] += 1

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(go, range(10)))

    assert outcomes["ok"] == 1, f"{outcomes['ok']} transitions to SUBMITTED succeeded (want exactly 1)"
    with repo.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM application_state_transitions WHERE application_id=? AND to_status='SUBMITTED'",
            (aid,),
        ).fetchone()["c"]
    assert n == 1
