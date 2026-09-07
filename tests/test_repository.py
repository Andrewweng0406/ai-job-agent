import pytest
from datetime import datetime, timedelta, timezone

from app.database.repository import JobAgentRepository
from app.applications.dry_run import DryRunTranscript
from app.models.application import Application
from app.models.enums import ApplicationStatus, JobFamily, Persona
from app.models.job import Job
from app.resumes.generator import ResumeArtifact


def test_repository_initializes_and_logs_state_transition(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Business Analyst",
            location="Chicago, IL",
            description="Entry-level business analyst.",
            source="fixture",
            source_url="https://example.test/job-1",
            apply_url="https://example.test/apply/job-1",
            ats_type="fixture",
            job_family=JobFamily.BUSINESS_SYSTEMS,
        )
    )
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Business Analyst",
        location="Chicago, IL",
        job_family=JobFamily.BUSINESS_SYSTEMS,
        source="fixture",
        ats_type="fixture",
    )
    repo.insert_application(app)
    repo.transition_application(app.application_id, ApplicationStatus.ELIGIBLE, "passed filters")

    with repo.connect() as conn:
        row = conn.execute("SELECT status FROM applications WHERE application_id = ?", (app.application_id,)).fetchone()
        transitions = conn.execute("SELECT COUNT(*) AS count FROM application_state_transitions").fetchone()
    assert row["status"] == "ELIGIBLE"
    assert transitions["count"] == 1


def test_insert_application_is_idempotent_by_dedupe_key(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Business Analyst",
            location="Chicago, IL",
            description="Entry-level business analyst.",
            source="fixture",
            source_url="https://example.test/job-1",
            apply_url="https://example.test/apply/job-1",
            ats_type="fixture",
            job_family=JobFamily.BUSINESS_SYSTEMS,
        )
    )
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Business Analyst",
        location="Chicago, IL",
        job_family=JobFamily.BUSINESS_SYSTEMS,
        source="fixture",
        ats_type="fixture",
        dedupe_key="candidate|acme|job-1",
    )
    first_id = repo.insert_application(app)
    second = Application(
        job_id=job_id,
        company="Acme",
        position="Business Analyst",
        location="Chicago, IL",
        job_family=JobFamily.BUSINESS_SYSTEMS,
        source="fixture",
        ats_type="fixture",
        dedupe_key="candidate|acme|job-1",
    )
    second_id = repo.insert_application(second)

    with repo.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM applications").fetchone()
    assert second_id == first_id
    assert count["count"] == 1


def test_foreign_keys_are_enforced(tmp_path):
    import sqlite3

    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    app = Application(
        job_id=999,
        company="Ghost",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="fixture",
        ats_type="fixture",
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_application(app)


def test_upsert_job_updates_mutable_columns(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="SQL",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
            job_family=JobFamily.DATA_ANALYTICS,
            salary_min=80000,
        )
    )
    updated_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="New York, NY",
            description="SQL and Python",
            source="fixture",
            source_url="https://example.test/job-updated",
            apply_url="https://example.test/apply-updated",
            ats_type="fixture",
            job_family=JobFamily.DATA_ANALYTICS,
            salary_min=90000,
            requirements=["Python"],
        )
    )

    with repo.connect() as conn:
        row = conn.execute(
            "SELECT location, salary_min, requirements_json, source_url, apply_url FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    assert updated_id == job_id
    assert row["location"] == "New York, NY"
    assert row["salary_min"] == 90000
    assert row["requirements_json"] == '["Python"]'
    assert row["source_url"] == "https://example.test/job-updated"
    assert row["apply_url"] == "https://example.test/apply-updated"


def test_resume_artifact_can_attach_to_application(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="SQL",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
            job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    app_id = repo.insert_application(
        Application(
            job_id=job_id,
            company="Acme",
            position="Data Analyst",
            location="Remote",
            job_family=JobFamily.DATA_ANALYTICS,
            source="fixture",
            ats_type="fixture",
        )
    )
    artifact = ResumeArtifact(
        resume_id="resume-1",
        job_id=job_id,
        persona=Persona.DATA,
        base_version="test",
        generated_at="2026-09-07T00:00:00+00:00",
        changes={},
        validation_status="VALIDATED",
        file_path="data/resumes/resume-1.txt",
        file_hash="abc",
    )
    repo.insert_resume_artifact(artifact)
    repo.attach_resume_to_application(app_id, artifact.resume_id)

    with repo.connect() as conn:
        row = conn.execute("SELECT resume_id FROM applications WHERE application_id = ?", (app_id,)).fetchone()
    assert row["resume_id"] == "resume-1"


def test_claim_next_application_is_lease_protected(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="SQL",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
            job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    app = Application(
        job_id=job_id,
        company="Acme",
        position="Data Analyst",
        location="Remote",
        job_family=JobFamily.DATA_ANALYTICS,
        source="fixture",
        ats_type="fixture",
        status=ApplicationStatus.READY,
    )
    app_id = repo.insert_application(app)
    lease = datetime.now(timezone.utc) + timedelta(minutes=5)

    first = repo.claim_next_application(ApplicationStatus.READY, "worker-1", lease)
    second = repo.claim_next_application(ApplicationStatus.READY, "worker-2", lease)

    assert first is not None
    assert first[0] == app_id
    assert first[1] == 1
    assert second is None
    assert repo.lease_still_mine(app_id, "worker-1", first[1])

    with repo.connect() as conn:
        row = conn.execute("SELECT status, worker_id, lease_epoch FROM applications WHERE application_id = ?", (app_id,)).fetchone()
        transitions = conn.execute(
            """
            SELECT from_status, to_status, reason
            FROM application_state_transitions
            WHERE application_id = ?
            """,
            (app_id,),
        ).fetchall()
    assert row["status"] == "APPLYING"
    assert row["worker_id"] == "worker-1"
    assert row["lease_epoch"] == 1
    assert [(t["from_status"], t["to_status"], t["reason"]) for t in transitions] == [
        ("READY", "APPLYING", "worker lease claimed")
    ]

    repo.release_lease(app_id, "worker-1", first[1])
    assert not repo.lease_still_mine(app_id, "worker-1", first[1])


def test_dry_run_transcript_is_persisted_with_hash(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    job_id = repo.upsert_job(
        Job(
            external_job_id="job-1",
            company_id="acme",
            company_name="Acme",
            title="Data Analyst",
            location="Remote",
            description="SQL",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
            job_family=JobFamily.DATA_ANALYTICS,
        )
    )
    app_id = repo.insert_application(
        Application(
            job_id=job_id,
            company="Acme",
            position="Data Analyst",
            location="Remote",
            job_family=JobFamily.DATA_ANALYTICS,
            source="fixture",
            ats_type="fixture",
            status=ApplicationStatus.READY,
        )
    )
    transcript = DryRunTranscript(
        application_id=app_id,
        job_id=job_id,
        payload={"fields": [{"name": "email", "value": "candidate@example.test"}]},
        would_submit=False,
        blocking_reasons=["REAL_SUBMISSION_DISABLED"],
    )

    transcript_id = repo.insert_dry_run_transcript(transcript)

    with repo.connect() as conn:
        row = conn.execute("SELECT * FROM dry_run_transcripts WHERE transcript_id = ?", (transcript_id,)).fetchone()
    assert row["application_id"] == app_id
    assert row["would_submit"] == 0
    assert row["blocking_json"] == '["REAL_SUBMISSION_DISABLED"]'
    assert row["payload_hash"] == transcript.payload_hash()
