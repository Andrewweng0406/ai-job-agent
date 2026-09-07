import json
import sqlite3

import pytest

from app.applications.greenhouse_dry_run import GreenhouseDryRunAdapter
from app.applications.preview import ApprovedAutofillPreviewBuilder
from tests.test_greenhouse_dry_run import GREENHOUSE_FORM, _Page, _profile, _seed_ready_with_resume


def test_approved_autofill_preview_requires_approval_and_hash_match(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    dry_run = _build_ready_transcript(repo, job, app_id)
    builder = ApprovedAutofillPreviewBuilder(repo)

    with pytest.raises(RuntimeError, match="not approved"):
        builder.build(dry_run.transcript.transcript_id)

    repo.approve_dry_run_transcript(dry_run.transcript.transcript_id, "human@example.test")
    preview = builder.build(dry_run.transcript.transcript_id)

    assert preview.application_id == app_id
    assert preview.approved_by == "human@example.test"
    assert {field["label"] for field in preview.fields} >= {"First Name *", "Email *", "Resume/CV *"}


def test_autofill_preview_rejects_mutated_payload_after_approval(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    dry_run = _build_ready_transcript(repo, job, app_id)
    transcript_id = dry_run.transcript.transcript_id
    repo.approve_dry_run_transcript(transcript_id, "human@example.test")
    mutated = dict(dry_run.transcript.payload)
    mutated["would_submit"] = False

    with pytest.raises(sqlite3.IntegrityError, match="payload is immutable"):
        with repo.connect() as conn:
            conn.execute(
                "UPDATE dry_run_transcripts SET payload_json = ? WHERE transcript_id = ?",
                (json.dumps(mutated, sort_keys=True), transcript_id),
            )

    preview = ApprovedAutofillPreviewBuilder(repo).build(transcript_id)
    assert preview.transcript_id == transcript_id


def test_autofill_preview_rejects_not_submit_ready_transcript(tmp_path):
    repo, job, app_id = _seed_ready_with_resume(tmp_path)
    dry_run = GreenhouseDryRunAdapter(repo).dry_run(
        page=_Page(GREENHOUSE_FORM),
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc",
        resume_validation_status="PDF_QA_FAILED",
    )
    transcript_id = dry_run.dry_run.transcript.transcript_id
    repo.approve_dry_run_transcript(transcript_id, "human@example.test")

    with pytest.raises(RuntimeError, match="not submit-ready"):
        ApprovedAutofillPreviewBuilder(repo).build(transcript_id)


def _build_ready_transcript(repo, job, app_id):
    result = GreenhouseDryRunAdapter(repo).dry_run(
        page=_Page(GREENHOUSE_FORM),
        application_id=app_id,
        job=job,
        profile=_profile(),
        resume_id="resume-1",
        resume_path="data/resumes/resume-1.pdf",
        resume_hash="sha256:abc",
        resume_validation_status="VALIDATED",
        persona="DATA",
    )
    assert result.dry_run is not None
    return result.dry_run
