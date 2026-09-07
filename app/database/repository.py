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
from app.applications.dry_run import DryRunTranscript
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
        for column_name in ("worker_id", "claimed_at", "lease_expires_at", "submit_attempted_at"):
            if column_name not in columns:
                try:
                    conn.execute(f"ALTER TABLE applications ADD COLUMN {column_name} TEXT")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
        if "lease_epoch" not in columns:
            try:
                conn.execute("ALTER TABLE applications ADD COLUMN lease_epoch INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_lease ON applications(lease_expires_at)")

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

    def list_jobs_by_status(self, status: str, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT id, company_name, title, location, job_family, status, source, apply_url
                    FROM jobs
                    WHERE status = ?
                    ORDER BY discovered_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            )

    def list_eligible_applications(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT a.application_id, a.status, a.company, a.position, a.location, a.job_family, a.ats_type, j.apply_url
                    FROM applications a
                    JOIN jobs j ON j.id = a.job_id
                    WHERE a.status IN ('ELIGIBLE', 'QUEUED', 'READY')
                    ORDER BY a.discovered_at ASC, a.application_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            )

    def get_next_application_with_job(self, status: ApplicationStatus) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT
                    a.application_id, a.company, a.position, a.persona, a.resume_id,
                    r.file_path AS resume_file_path, r.file_hash AS resume_file_hash,
                    r.validation_status AS resume_validation_status,
                    j.id AS job_id, j.external_job_id, j.company_id, j.company_name,
                    j.title, j.normalized_title, j.job_family, j.location, j.remote_status,
                    j.employment_type, j.salary_min, j.salary_max, j.currency, j.description,
                    j.source, j.source_url, j.apply_url, j.ats_type, j.description_hash
                FROM applications a
                JOIN jobs j ON j.id = a.job_id
                LEFT JOIN resumes r ON r.resume_id = a.resume_id
                WHERE a.status = ?
                  AND (a.lease_expires_at IS NULL OR a.lease_expires_at < ?)
                ORDER BY a.queued_at ASC, a.application_id ASC
                LIMIT 1
                """,
                (status.value, dt(datetime.now(timezone.utc))),
            ).fetchone()

    def get_application_with_job(self, application_id: str):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT
                    a.application_id, a.company, a.position, a.persona, a.resume_id,
                    r.file_path AS resume_file_path, r.file_hash AS resume_file_hash,
                    r.validation_status AS resume_validation_status,
                    j.id AS job_id, j.external_job_id, j.company_id, j.company_name,
                    j.title, j.normalized_title, j.job_family, j.location, j.remote_status,
                    j.employment_type, j.salary_min, j.salary_max, j.currency, j.description,
                    j.source, j.source_url, j.apply_url, j.ats_type, j.description_hash
                FROM applications a
                JOIN jobs j ON j.id = a.job_id
                LEFT JOIN resumes r ON r.resume_id = a.resume_id
                WHERE a.application_id = ?
                """,
                (application_id,),
            ).fetchone()

    def discovery_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
            filter_rows = conn.execute("SELECT COALESCE(reason, 'ALLOWED') AS reason, COUNT(*) AS count FROM job_filter_results GROUP BY reason").fetchall()
        stats = {f"jobs_{row['status'].lower()}": row["count"] for row in rows}
        stats.update({f"filter_{row['reason'].lower()}": row["count"] for row in filter_rows})
        return stats

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

    def claim_next_application(self, status: ApplicationStatus, worker_id: str, lease_expires_at: datetime) -> tuple[str, int] | None:
        machine = ApplicationStateMachine()
        now = datetime.now(timezone.utc)
        target = ApplicationStatus.APPLYING if status in {ApplicationStatus.READY, ApplicationStatus.RETRY_PENDING} else status
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT application_id, status
                FROM applications
                WHERE status = ?
                  AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                  AND submit_attempted_at IS NULL
                  AND submit_attempted_at IS NULL
                ORDER BY queued_at ASC, application_id ASC
                LIMIT 1
                """,
                (status.value, dt(now)),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            transition = machine.transition(ApplicationStatus(row["status"]), target, "worker lease claimed")
            cursor = conn.execute(
                """
                UPDATE applications
                SET status = ?, worker_id = ?, claimed_at = ?, lease_expires_at = ?, lease_epoch = lease_epoch + 1
                WHERE application_id = ?
                  AND status = ?
                  AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                  AND submit_attempted_at IS NULL
                """,
                (target.value, worker_id, dt(now), dt(lease_expires_at), row["application_id"], status.value, dt(now)),
            )
            if cursor.rowcount != 1:
                conn.execute("ROLLBACK")
                return None
            conn.execute(
                """
                INSERT INTO application_state_transitions (application_id, from_status, to_status, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["application_id"],
                    transition.from_status.value,
                    transition.to_status.value,
                    transition.reason,
                    dt(now),
                ),
            )
            epoch_row = conn.execute("SELECT lease_epoch FROM applications WHERE application_id = ?", (row["application_id"],)).fetchone()
            conn.execute("COMMIT")
        return str(row["application_id"]), int(epoch_row["lease_epoch"])

    def lease_still_mine(self, application_id: str, worker_id: str, lease_epoch: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM applications
                WHERE application_id = ?
                  AND worker_id = ?
                  AND lease_epoch = ?
                  AND lease_expires_at > ?
                """,
                (application_id, worker_id, lease_epoch, dt(datetime.now(timezone.utc))),
            ).fetchone()
            return row is not None

    def release_lease(self, application_id: str, worker_id: str, lease_epoch: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE applications
                SET worker_id = NULL, claimed_at = NULL, lease_expires_at = NULL
                WHERE application_id = ? AND worker_id = ? AND lease_epoch = ?
                """,
                (application_id, worker_id, lease_epoch),
            )

    def reap_expired_leases(self, *, grace_seconds: int = 0, now: datetime | None = None) -> list[tuple[str, ApplicationStatus]]:
        machine = ApplicationStateMachine()
        current_time = now or datetime.now(timezone.utc)
        cutoff = current_time.timestamp() - grace_seconds
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        reaped: list[tuple[str, ApplicationStatus]] = []
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT application_id, status, submit_attempted_at
                FROM applications
                WHERE status IN ('APPLYING', 'TAILORING')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                ORDER BY lease_expires_at ASC, application_id ASC
                """,
                (dt(cutoff_dt),),
            ).fetchall()
            for row in rows:
                current = ApplicationStatus(row["status"])
                target = (
                    ApplicationStatus.SUBMISSION_UNKNOWN
                    if current == ApplicationStatus.APPLYING and row["submit_attempted_at"]
                    else ApplicationStatus.RETRY_PENDING
                )
                transition = machine.transition(current, target, "expired worker lease reaped")
                cursor = conn.execute(
                    """
                    UPDATE applications
                    SET status = ?, worker_id = NULL, claimed_at = NULL, lease_expires_at = NULL
                    WHERE application_id = ? AND status = ?
                    """,
                    (target.value, row["application_id"], current.value),
                )
                if cursor.rowcount != 1:
                    continue
                conn.execute(
                    """
                    INSERT INTO application_state_transitions (application_id, from_status, to_status, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        row["application_id"],
                        transition.from_status.value,
                        transition.to_status.value,
                        transition.reason,
                        dt(current_time),
                    ),
                )
                reaped.append((str(row["application_id"]), target))
            conn.execute("COMMIT")
        return reaped

    def get_application_status(self, application_id: str) -> ApplicationStatus:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status FROM applications WHERE application_id = ?",
                (application_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown application_id: {application_id}")
        return ApplicationStatus(row["status"])

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

    def increment_attempt_count(self, application_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE applications SET attempt_count = attempt_count + 1 WHERE application_id = ?",
                (application_id,),
            )

    def mark_submit_attempted(self, application_id: str, attempted_at: datetime | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE applications SET submit_attempted_at = ? WHERE application_id = ?",
                (dt(attempted_at or datetime.now(timezone.utc)), application_id),
            )

    def set_applied_at_now(self, application_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE applications SET applied_at = ? WHERE application_id = ?",
                (dt(datetime.now(timezone.utc)), application_id),
            )

    def mark_human_required(self, application_id: str, reason: str, task: HumanTask | None = None) -> None:
        machine = ApplicationStateMachine()
        now = datetime.now(timezone.utc)
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
            if task is None:
                task = HumanTask(
                    application_id=application_id,
                    category=reason,
                    blocking_state=current.value,
                    prompt=f"Human review required: {reason}",
                    context={"reason": reason, "previous_status": current.value},
                )
            transition = machine.transition(current, ApplicationStatus.HUMAN_REQUIRED, reason)
            conn.execute(
                "UPDATE applications SET status = ?, human_required_reason = ? WHERE application_id = ? AND status = ?",
                (ApplicationStatus.HUMAN_REQUIRED.value, reason, application_id, current.value),
            )
            conn.execute(
                """
                INSERT INTO application_state_transitions (application_id, from_status, to_status, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (application_id, transition.from_status.value, transition.to_status.value, reason, dt(now)),
            )
            if task is not None:
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
                    _human_task_values(task, now),
                )
            conn.execute("COMMIT")

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

    def merge_confirmation_data(self, application_id: str, confirmation_data: dict[str, object]) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT confirmation_data_json FROM applications WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown application_id: {application_id}")
            current = json.loads(row["confirmation_data_json"] or "{}")
            current.update(confirmation_data)
            conn.execute(
                "UPDATE applications SET confirmation_data_json = ? WHERE application_id = ?",
                (json.dumps(current, sort_keys=True), application_id),
            )

    def set_submission_verified_at(self, application_id: str, verified_at: datetime) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE applications SET submission_verified_at = ? WHERE application_id = ?",
                (dt(verified_at), application_id),
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

    def insert_dry_run_transcript(self, transcript: DryRunTranscript) -> str:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO dry_run_transcripts (
                    transcript_id, application_id, job_id, created_at, generator_version,
                    would_submit, blocking_json, payload_json, payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transcript.transcript_id,
                    transcript.application_id,
                    transcript.job_id,
                    dt(transcript.created_at),
                    transcript.generator_version,
                    int(transcript.would_submit),
                    json.dumps(transcript.blocking_reasons),
                    transcript.payload_json(),
                    transcript.payload_hash(),
                ),
            )
            return transcript.transcript_id

    def approve_dry_run_transcript(self, transcript_id: str, approved_by: str, approved_at: datetime | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE dry_run_transcripts
                SET approved_by = ?, approved_at = ?
                WHERE transcript_id = ?
                """,
                (approved_by, dt(approved_at or datetime.now(timezone.utc)), transcript_id),
            )

    def dry_run_approval_is_valid(self, transcript_id: str, payload_hash: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT approved_by, approved_at, payload_hash
                FROM dry_run_transcripts
                WHERE transcript_id = ?
                """,
                (transcript_id,),
            ).fetchone()
        return row is not None and bool(row["approved_by"]) and bool(row["approved_at"]) and row["payload_hash"] == payload_hash

    def get_dry_run_transcript(self, transcript_id: str):
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT transcript_id, application_id, job_id, created_at, generator_version,
                       would_submit, blocking_json, payload_json, payload_hash, approved_by, approved_at
                FROM dry_run_transcripts
                WHERE transcript_id = ?
                """,
                (transcript_id,),
            ).fetchone()

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
                "UPDATE applications SET status = ?, submit_attempted_at = CASE WHEN ? = 'SKIPPED' THEN NULL ELSE submit_attempted_at END WHERE application_id = ? AND status = ?",
                (target.value, target.value, application_id, current.value),
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


def _human_task_values(task: HumanTask, now: datetime) -> tuple[object, ...]:
    return (
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
        dt(task.created_at or now),
        dt(task.updated_at or now),
        dt(task.expires_at),
    )


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
