"""Submission-verification red team (WS7).

Evidence tiers T1-T5 / UNKNOWN, via app.tracking.verification.
- strong evidence (T1-T4) -> VERIFIED
- weak / ambiguous -> NOT VERIFIED (stays SUBMITTED, later SUBMISSION_UNKNOWN)
- HTTP 200 + validation error -> NOT VERIFIED
- duplicate evidence -> no duplicate transition rows
- SUBMISSION_UNKNOWN + later T3 email -> VERIFIED
"""
from __future__ import annotations

import pytest

from app.database.repository import JobAgentRepository
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily
from app.models.job import Job
from app.tracking.verification import EvidenceTier, VerificationEvidence, VerificationService


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "verif.sqlite3")
    r.initialize()
    return r


def _submitted_app(repo) -> str:
    job_id = repo.upsert_job(
        Job(external_job_id="job-1", company_id="acme", company_name="Acme", title="Data Analyst",
            location="Remote", description="x", source="fixture", source_url="https://e.test/1",
            apply_url="https://e.test/apply/1", ats_type="fixture", job_family=JobFamily.DATA_ANALYTICS)
    )
    a = Application(job_id=job_id, company="Acme", position="Data Analyst", location="Remote",
                    job_family=JobFamily.DATA_ANALYTICS, source="fixture", ats_type="fixture")
    repo.insert_application(a)
    for s in [ApplicationStatus.ELIGIBLE, ApplicationStatus.QUEUED, ApplicationStatus.TAILORING,
              ApplicationStatus.READY, ApplicationStatus.APPLYING, ApplicationStatus.SUBMITTED]:
        repo.transition_application(a.application_id, s, "seed")
    return a.application_id


@pytest.mark.parametrize(
    "tier",
    [EvidenceTier.T1_CONFIRMATION_ID, EvidenceTier.T2_BACKEND_SUCCESS,
     EvidenceTier.T3_CONFIRMATION_EMAIL, EvidenceTier.T4_PORTAL_ENTRY],
)
def test_strong_evidence_verifies(tmp_path, tier):
    repo = _repo(tmp_path)
    app_id = _submitted_app(repo)
    status = VerificationService(repo).record_evidence(
        app_id, VerificationEvidence(tier=tier, source="fixture", confirmation_id="R-1")
    )
    assert status == ApplicationStatus.VERIFIED
    assert repo.get_application_status(app_id) == ApplicationStatus.VERIFIED


def test_weak_page_text_does_not_verify(tmp_path):
    repo = _repo(tmp_path)
    app_id = _submitted_app(repo)
    status = VerificationService(repo).record_evidence(
        app_id,
        VerificationEvidence(tier=EvidenceTier.T5_WEAK_PAGE_TEXT, source="fixture",
                             success_page_text_match="Thank you"),
    )
    assert status != ApplicationStatus.VERIFIED
    assert repo.get_application_status(app_id) == ApplicationStatus.SUBMITTED


def test_generic_thanks_without_context_is_weak(tmp_path):
    """A bare 'Thank you' with no application/requisition context must not be strong evidence."""
    repo = _repo(tmp_path)
    app_id = _submitted_app(repo)
    ev = VerificationEvidence(tier=EvidenceTier.T5_WEAK_PAGE_TEXT, source="fixture",
                              success_page_text_match="Thank you")
    assert ev.is_strong() is False
    VerificationService(repo).record_evidence(app_id, ev)
    assert repo.get_application_status(app_id) == ApplicationStatus.SUBMITTED


def test_http_200_with_validation_error_is_not_verified(tmp_path):
    """Caller must classify a 200 that contains a validation error as NOT evidence.

    The verification layer only accepts explicit tiers; passing a weak tier keeps it SUBMITTED.
    """
    repo = _repo(tmp_path)
    app_id = _submitted_app(repo)
    # simulate: adapter saw HTTP 200 but the page had '.field_with_errors' -> it must NOT
    # construct a strong VerificationEvidence. Best it can honestly claim is T5.
    status = VerificationService(repo).record_evidence(
        app_id, VerificationEvidence(tier=EvidenceTier.T5_WEAK_PAGE_TEXT, source="fixture")
    )
    assert status != ApplicationStatus.VERIFIED


def test_duplicate_strong_evidence_does_not_double_transition(tmp_path):
    repo = _repo(tmp_path)
    app_id = _submitted_app(repo)
    svc = VerificationService(repo)
    ev = VerificationEvidence(tier=EvidenceTier.T1_CONFIRMATION_ID, source="fixture", confirmation_id="R-1")
    svc.record_evidence(app_id, ev)
    # second delivery of the same evidence (e.g. verify worker retried)
    with pytest.raises(Exception):
        svc.record_evidence(app_id, ev)  # already VERIFIED -> cannot verify again
    with repo.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM application_state_transitions WHERE application_id=? AND to_status='VERIFIED'",
            (app_id,),
        ).fetchone()["c"]
    assert n == 1, "exactly one VERIFIED transition"


def test_submission_unknown_promoted_by_later_email(tmp_path):
    repo = _repo(tmp_path)
    app_id = _submitted_app(repo)
    repo.transition_application(app_id, ApplicationStatus.SUBMISSION_UNKNOWN, "no evidence in window")
    status = VerificationService(repo).record_evidence(
        app_id,
        VerificationEvidence(tier=EvidenceTier.T3_CONFIRMATION_EMAIL, source="mailbox",
                             email_message_id="<abc@ats.com>"),
    )
    assert status == ApplicationStatus.VERIFIED
    assert repo.get_application_status(app_id) == ApplicationStatus.VERIFIED
