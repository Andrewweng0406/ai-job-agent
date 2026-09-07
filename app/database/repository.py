from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
import json
import sqlite3

from app.applications.state_machine import ApplicationStateMachine
from app.database.schema import SCHEMA_SQL
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job


def dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class JobAgentRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def upsert_job(self, job: Job) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    external_job_id, company_id, company_name, title, normalized_title, job_family,
                    location, remote_status, employment_type, salary_min, salary_max, currency,
                    description, requirements_json, preferred_qualifications_json, posted_at,
                    discovered_at, source, source_url, apply_url, ats_type, description_hash,
                    status, raw_data_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, external_job_id) DO UPDATE SET
                    title=excluded.title,
                    normalized_title=excluded.normalized_title,
                    job_family=excluded.job_family,
                    location=excluded.location,
                    description=excluded.description,
                    description_hash=excluded.description_hash,
                    status=excluded.status,
                    metadata_json=excluded.metadata_json
                """,
                (
                    job.external_job_id,
                    job.company_id,
                    job.company_name,
                    job.title,
                    job.normalized_title,
                    job.job_family.value,
                    job.location,
                    job.remote_status,
                    job.employment_type,
                    job.salary_min,
                    job.salary_max,
                    job.currency,
                    job.description,
                    json.dumps(job.requirements),
                    json.dumps(job.preferred_qualifications),
                    dt(job.posted_at),
                    dt(job.discovered_at),
                    job.source,
                    job.source_url,
                    job.apply_url,
                    job.ats_type,
                    job.description_hash,
                    job.status.value,
                    json.dumps(job.raw_data, sort_keys=True),
                    json.dumps(job.metadata, sort_keys=True),
                ),
            )
            row = conn.execute(
                "SELECT id FROM jobs WHERE source = ? AND external_job_id = ?",
                (job.source, job.external_job_id),
            ).fetchone()
            return int(row["id"])

    def insert_application(self, application: Application) -> str:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO applications (
                    application_id, job_id, company, position, location, job_family, source,
                    ats_type, match_score, persona, resume_id, discovered_at, queued_at,
                    applied_at, submission_verified_at, status, attempt_count, failure_category,
                    failure_reason, human_required_reason, confirmation_data_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application.application_id,
                    application.job_id,
                    application.company,
                    application.position,
                    application.location,
                    application.job_family.value,
                    application.source,
                    application.ats_type,
                    application.match_score,
                    application.persona.value if application.persona else None,
                    application.resume_id,
                    dt(application.discovered_at),
                    dt(application.queued_at),
                    dt(application.applied_at),
                    dt(application.submission_verified_at),
                    application.status.value,
                    application.attempt_count,
                    application.failure_category.value if application.failure_category else None,
                    application.failure_reason,
                    application.human_required_reason,
                    json.dumps(application.confirmation_data, sort_keys=True),
                    application.notes,
                ),
            )
            return application.application_id

    def application_exists_for_job(self, job_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM applications WHERE job_id = ?", (job_id,)).fetchone()
            return row is not None

    def record_job_filter_result(self, job_id: int, allowed: bool, reason: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO job_filter_results (job_id, allowed, reason) VALUES (?, ?, ?)",
                (job_id, int(allowed), reason),
            )

    def transition_application(self, application_id: str, target: ApplicationStatus, reason: str) -> None:
        machine = ApplicationStateMachine()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status FROM applications WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown application_id: {application_id}")
            current = ApplicationStatus(row["status"])
            transition = machine.transition(current, target, reason)
            conn.execute(
                "UPDATE applications SET status = ? WHERE application_id = ?",
                (target.value, application_id),
            )
            conn.execute(
                """
                INSERT INTO application_state_transitions (application_id, from_status, to_status, reason)
                VALUES (?, ?, ?, ?)
                """,
                (application_id, transition.from_status.value, transition.to_status.value, transition.reason),
            )
