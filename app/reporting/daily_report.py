from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class DailyReport:
    report_date: date
    target_submissions: int
    verified_submissions: int
    attempts: int
    jobs_discovered: int
    eligible_jobs: int
    skipped_jobs: int
    blocked_human_required: int
    failed_applications: int
    by_status: dict[str, int] = field(default_factory=dict)
    by_ats: dict[str, int] = field(default_factory=dict)
    by_family: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = [
            f"# Daily Report - {self.report_date.isoformat()}",
            "",
            f"- Target submissions: {self.target_submissions}",
            f"- Verified submissions: {self.verified_submissions}",
            f"- Attempts: {self.attempts}",
            f"- Jobs discovered: {self.jobs_discovered}",
            f"- Eligible jobs: {self.eligible_jobs}",
            f"- Skipped jobs: {self.skipped_jobs}",
            f"- Human-required: {self.blocked_human_required}",
            f"- Failed applications: {self.failed_applications}",
            "",
            "## Status Breakdown",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.by_status.items()))
        lines.append("")
        lines.append("## ATS Breakdown")
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.by_ats.items()))
        lines.append("")
        lines.append("## Job Family Breakdown")
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.by_family.items()))
        return "\n".join(lines)


def build_daily_report(
    repository,
    report_date: date,
    target_submissions: int,
    timezone_name: str = "America/Los_Angeles",
) -> DailyReport:
    tz = ZoneInfo(timezone_name)
    with repository.connect() as conn:
        job_rows = conn.execute("SELECT discovered_at FROM jobs").fetchall()
        filter_rows = conn.execute("SELECT allowed, created_at FROM job_filter_results").fetchall()
        by_status = _counts(conn, "SELECT status AS key, COUNT(*) AS count FROM applications GROUP BY status")
        by_ats = _counts(conn, "SELECT ats_type AS key, COUNT(*) AS count FROM applications WHERE status = 'VERIFIED' GROUP BY ats_type")
        by_family = _counts(conn, "SELECT job_family AS key, COUNT(*) AS count FROM applications WHERE status = 'VERIFIED' GROUP BY job_family")

    jobs_discovered = sum(1 for row in job_rows if _on_report_date(row["discovered_at"], report_date, tz))
    skipped_jobs = sum(1 for row in filter_rows if not row["allowed"] and _on_report_date(row["created_at"], report_date, tz))
    eligible_jobs = sum(1 for row in filter_rows if row["allowed"] and _on_report_date(row["created_at"], report_date, tz))
    attempts = sum(by_status.get(status, 0) for status in ("APPLYING", "SUBMITTED", "SUBMISSION_UNKNOWN", "VERIFIED", "FAILED"))
    return DailyReport(
        report_date=report_date,
        target_submissions=target_submissions,
        verified_submissions=by_status.get("VERIFIED", 0),
        attempts=attempts,
        jobs_discovered=jobs_discovered,
        eligible_jobs=eligible_jobs,
        skipped_jobs=skipped_jobs,
        blocked_human_required=by_status.get("HUMAN_REQUIRED", 0),
        failed_applications=by_status.get("FAILED", 0),
        by_status=by_status,
        by_ats=by_ats,
        by_family=by_family,
    )


def _counts(conn, sql: str) -> dict[str, int]:
    return {row["key"]: row["count"] for row in conn.execute(sql).fetchall()}


def _on_report_date(value: str, report_date: date, tz: ZoneInfo) -> bool:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz).date() == report_date
