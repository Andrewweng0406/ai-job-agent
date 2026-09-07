import pytest

from app.applications.dry_run_worker import DryRunApplicationWorker
from app.database.repository import JobAgentRepository
from app.models.enums import ApplicationStatus
from tests.test_ats_dom_dry_run import LEVER_FORM, _seed_ready_with_resume
from tests.test_greenhouse_dry_run import _Page, _profile


def test_dry_run_worker_refuses_real_submission_mode(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.db")

    with pytest.raises(ValueError, match="real_submission_enabled=False"):
        DryRunApplicationWorker(
            repo,
            worker_id="worker-1",
            profile=_profile(),
            page_provider=lambda application_id, job: _Page(LEVER_FORM),
            real_submission_enabled=True,
        )


def test_dry_run_worker_claims_runs_transcript_and_releases_lease(tmp_path):
    repo, _job, app_id = _seed_ready_with_resume(tmp_path, "lever")
    pages = []

    def page_provider(application_id, job):
        pages.append((application_id, job.ats_type))
        return _Page(LEVER_FORM)

    result = DryRunApplicationWorker(
        repo,
        worker_id="worker-1",
        profile=_profile(),
        page_provider=page_provider,
    ).run_once()

    assert result.status == ApplicationStatus.READY
    assert result.application_id == app_id
    assert pages == [(app_id, "lever")]
    assert repo.get_application_status(app_id) == ApplicationStatus.READY
    with repo.connect() as conn:
        app = conn.execute(
            "SELECT worker_id, lease_expires_at FROM applications WHERE application_id = ?",
            (app_id,),
        ).fetchone()
        transcripts = conn.execute(
            "SELECT COUNT(*) AS count FROM dry_run_transcripts WHERE application_id = ?",
            (app_id,),
        ).fetchone()
    assert app["worker_id"] is None
    assert app["lease_expires_at"] is None
    assert transcripts["count"] == 1


def test_dry_run_worker_aborts_without_side_effect_when_lease_is_stale(tmp_path):
    repo, _job, app_id = _seed_ready_with_resume(tmp_path, "lever")
    stale_repo = _StaleLeaseRepository(repo.database_path)
    page_calls = []

    result = DryRunApplicationWorker(
        stale_repo,
        worker_id="stale-worker",
        profile=_profile(),
        page_provider=lambda application_id, job: page_calls.append(application_id) or _Page(LEVER_FORM),
    ).run_once()

    assert result.status == ApplicationStatus.APPLYING
    assert result.reason == "LEASE_LOST"
    assert result.application_id == app_id
    assert page_calls == []
    with repo.connect() as conn:
        transcripts = conn.execute(
            "SELECT COUNT(*) AS count FROM dry_run_transcripts WHERE application_id = ?",
            (app_id,),
        ).fetchone()
    assert transcripts["count"] == 0


def test_dry_run_worker_rechecks_lease_after_page_load(tmp_path):
    repo, _job, app_id = _seed_ready_with_resume(tmp_path, "lever")
    expiring_repo = _ExpiringLeaseRepository(repo.database_path)

    result = DryRunApplicationWorker(
        expiring_repo,
        worker_id="expiring-worker",
        profile=_profile(),
        page_provider=lambda application_id, job: _Page(LEVER_FORM),
    ).run_once()

    assert result.status == ApplicationStatus.APPLYING
    assert result.reason == "LEASE_LOST"
    assert expiring_repo.lease_checks == 2
    with repo.connect() as conn:
        transcripts = conn.execute(
            "SELECT COUNT(*) AS count FROM dry_run_transcripts WHERE application_id = ?",
            (app_id,),
        ).fetchone()
    assert transcripts["count"] == 0


class _StaleLeaseRepository:
    def __init__(self, database_path) -> None:
        self._repo = JobAgentRepository(database_path)
        self.database_path = database_path

    def __getattr__(self, name):
        return getattr(self._repo, name)

    def lease_still_mine(self, application_id: str, worker_id: str, lease_epoch: int) -> bool:
        return False


class _ExpiringLeaseRepository(_StaleLeaseRepository):
    def __init__(self, database_path) -> None:
        super().__init__(database_path)
        self.lease_checks = 0

    def lease_still_mine(self, application_id: str, worker_id: str, lease_epoch: int) -> bool:
        self.lease_checks += 1
        return self.lease_checks == 1
