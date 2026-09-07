from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
import json
import sqlite3

from app.applications.state_machine import ApplicationStateMachine
from app.database.schema import SCHEMA_SQL
from app.models.application import Application
from app.models.enums import ApplicationStatus
from app.models.job import Job, stable_hash
from app.applications.human_tasks import HumanTask
from app.resumes.generator import ResumeArtifact, artifact_to_db_tuple


def dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class JobAgentRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate_existing_database(conn)

    def _migrate_existing_database(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(applications)").fetchall()}
        if "dedupe_key" not in columns:
            try:
                conn.execute("ALTER TABLE applications ADD COLUMN dedupe_key TEXT")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        rows = conn.execute("SELECT application_id, job_id FROM applications WHERE dedupe_key IS NULL").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE applications SET dedupe_key = ? WHERE application_id = ?",
                (_application_dedupe_key(row["job_id"]), row["application_id"]),
            )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_dedupe_key ON applications(dedupe_key)")

    def upsert_job(self, job: Job) -> int:
        with self.connect() as conn:
            try:
                conn.execute(_UPSERT_JOB_SQL, _job_values(job))
            except sqlite3.IntegrityError as exc:
                if "apply_url" not in str(exc).lower():
                    raise
                conn.execute(_UPDATE_JOB_BY_APPLY_URL_SQL, _job_update_values(job) + (job.apply_url,))
            row = conn.execute(
                "SELECT id FROM jobs WHERE source = ? AND external_job_id = ?",
                (job.source, job.external_job_id),
            ).fetchone()
            if row is None:
                row = conn.execute("SELECT id FROM jobs WHERE apply_url = ?", (job.apply_url,)).fetchone()
            return int(row["id"])

    def insert_application(self, application: Application) -> str:
        dedupe_key = application.dedupe_key or _application_dedupe_key(application.job_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO applications (
                    application_id, dedupe_key, job_id, company, position, location, job_family, source,
                    ats_type, match_score, persona, resume_id, discovered_at, queued_at,
                    applied_at, submission_verified_at, status, attempt_count, failure_category,
                    failure_reason, human_required_reason, confirmation_data_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (
                    application.application_id,
                    dedupe_key,
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
            row = conn.execute(
                "SELECT application_id FROM applications WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            return str(row["application_id"])

    def application_exists_for_job(self, job_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM applications WHERE job_id = ?", (job_id,)).fetchone()
            return row is not None

    def get_applications_by_status(self, status: ApplicationStatus, limit: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT application_id, job_family, status
                FROM applications
                WHERE status = ?
                ORDER BY discovered_at ASC, application_id ASC
                LIMIT ?
                """,
                (status.value, limit),
            ).fetchall()
            return list(rows)

    def update_application_context(self, application_id: str, *, persona: str | None = None, queued_at: str | None = None) -> None:
        updates: list[str] = []
        values: list[str] = []
        if persona is not None:
            updates.append("persona = ?")
            values.append(persona)
        if queued_at is not None:
            updates.append("queued_at = ?")
            values.append(queued_at)
        if not updates:
            return
        values.append(application_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE applications SET {', '.join(updates)} WHERE application_id = ?", values)

    def mark_human_required(self, application_id: str, reason: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status FROM applications WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown application_id: {application_id}")
        self.transition_application(application_id, ApplicationStatus.HUMAN_REQUIRED, reason)
        with self.connect() as conn:
            conn.execute(
                "UPDATE applications SET human_required_reason = ? WHERE application_id = ?",
                (reason, application_id),
            )

    def record_job_filter_result(self, job_id: int, allowed: bool, reason: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO job_filter_results (job_id, allowed, reason, created_at) VALUES (?, ?, ?, ?)",
                (job_id, int(allowed), reason, dt(datetime.now(timezone.utc))),
            )

    def insert_resume_artifact(self, artifact: ResumeArtifact) -> str:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO resumes (
                    resume_id, job_id, persona, base_version, generated_at, changes_json,
                    validation_status, file_path, file_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                artifact_to_db_tuple(artifact),
            )
            return artifact.resume_id

    def attach_resume_to_application(self, application_id: str, resume_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE applications SET resume_id = ? WHERE application_id = ?",
                (resume_id, application_id),
            )

    def open_human_task(self, task: HumanTask) -> str:
        now = datetime.now(timezone.utc)
        created_at = dt(task.created_at or now)
        updated_at = dt(task.updated_at or now)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO human_tasks (
                    task_id, application_id, job_id, category, status, blocking_state, prompt,
                    options_json, context_json, resume_token, resolution_json, resolved_by,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(application_id, category) WHERE status IN ('OPEN', 'IN_PROGRESS') DO UPDATE SET
                    prompt=excluded.prompt,
                    context_json=excluded.context_json,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.application_id,
                    task.job_id,
                    task.category,
                    task.status,
                    task.blocking_state,
                    task.prompt,
                    json.dumps(task.options),
                    json.dumps(task.context, sort_keys=True),
                    task.resume_token,
                    json.dumps(task.resolution, sort_keys=True) if task.resolution else None,
                    task.resolved_by,
                    created_at,
                    updated_at,
                    dt(task.expires_at),
                ),
            )
            row = conn.execute(
                """
                SELECT task_id FROM human_tasks
                WHERE category = ?
                  AND status IN ('OPEN', 'IN_PROGRESS')
                  AND (application_id = ? OR (application_id IS NULL AND ? IS NULL))
                """,
                (task.category, task.application_id, task.application_id),
            ).fetchone()
            return str(row["task_id"])

    def transition_application(self, application_id: str, target: ApplicationStatus, reason: str) -> None:
        machine = ApplicationStateMachine()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM applications WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise KeyError(f"Unknown application_id: {application_id}")
            current = ApplicationStatus(row["status"])
            transition = machine.transition(current, target, reason)
            cursor = conn.execute(
                "UPDATE applications SET status = ? WHERE application_id = ? AND status = ?",
                (target.value, application_id, current.value),
            )
            if cursor.rowcount != 1:
                conn.execute("ROLLBACK")
                raise RuntimeError(f"Concurrent status modification for application_id: {application_id}")
            conn.execute(
                """
                INSERT INTO application_state_transitions (application_id, from_status, to_status, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    application_id,
                    transition.from_status.value,
                    transition.to_status.value,
                    transition.reason,
                    dt(datetime.now(timezone.utc)),
                ),
            )
            conn.execute("COMMIT")


def _application_dedupe_key(job_id: int) -> str:
    return stable_hash(f"default_candidate|job:{job_id}")


_UPSERT_JOB_SQL = """
INSERT INTO jobs (
    external_job_id, company_id, company_name, title, normalized_title, job_family,
    location, remote_status, employment_type, salary_min, salary_max, currency,
    description, requirements_json, preferred_qualifications_json, posted_at,
    discovered_at, source, source_url, apply_url, ats_type, description_hash,
    status, raw_data_json, metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(source, external_job_id) DO UPDATE SET
    company_id=excluded.company_id,
    company_name=excluded.company_name,
    title=excluded.title,
    normalized_title=excluded.normalized_title,
    job_family=excluded.job_family,
    location=excluded.location,
    remote_status=excluded.remote_status,
    employment_type=excluded.employment_type,
    salary_min=excluded.salary_min,
    salary_max=excluded.salary_max,
    currency=excluded.currency,
    description=excluded.description,
    requirements_json=excluded.requirements_json,
    preferred_qualifications_json=excluded.preferred_qualifications_json,
    posted_at=excluded.posted_at,
    source_url=excluded.source_url,
    apply_url=excluded.apply_url,
    ats_type=excluded.ats_type,
    description_hash=excluded.description_hash,
    status=excluded.status,
    raw_data_json=excluded.raw_data_json,
    metadata_json=excluded.metadata_json
"""

_UPDATE_JOB_BY_APPLY_URL_SQL = """
UPDATE jobs SET
    external_job_id=?,
    company_id=?,
    company_name=?,
    title=?,
    normalized_title=?,
    job_family=?,
    location=?,
    remote_status=?,
    employment_type=?,
    salary_min=?,
    salary_max=?,
    currency=?,
    description=?,
    requirements_json=?,
    preferred_qualifications_json=?,
    posted_at=?,
    discovered_at=?,
    source=?,
    source_url=?,
    ats_type=?,
    description_hash=?,
    status=?,
    raw_data_json=?,
    metadata_json=?
WHERE apply_url=?
"""


def _job_values(job: Job) -> tuple[object, ...]:
    return (
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
    )


def _job_update_values(job: Job) -> tuple[object, ...]:
    values = list(_job_values(job))
    values.pop(19)
    return tuple(values)
