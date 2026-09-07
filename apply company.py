from __future__ import annotations

import argparse
from datetime import date

from app.database.repository import JobAgentRepository
from app.discovery.pipeline import DiscoveryPipeline
from app.matching.taxonomy import RoleTaxonomy
from app.applications.queue import ApplicationQueue
from app.reporting.daily_report import build_daily_report
from app.services.company_registry import load_company_registry
from app.utils.config import load_yaml
from app.utils.logging import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous new-grad job application agent.")
    parser.add_argument("--init-db", action="store_true", help="Initialize the local SQLite database schema.")
    parser.add_argument("--discover", action="store_true", help="Run read-only job discovery for configured companies.")
    parser.add_argument("--queue-eligible", action="store_true", help="Move eligible applications into the queue.")
    parser.add_argument("--daily-report", action="store_true", help="Print today's daily KPI report.")
    parser.add_argument("--limit", type=int, default=100, help="Limit for queueing operations.")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML.")
    parser.add_argument("--companies", default="config/companies.yaml", help="Path to company registry YAML.")
    parser.add_argument("--taxonomy", default="config/role_taxonomy.yaml", help="Path to role taxonomy YAML.")
    args = parser.parse_args()

    configure_logging()
    settings = load_yaml(args.settings)
    repo = JobAgentRepository(settings.get("database_path", "data/job_agent.sqlite3"))

    if args.init_db:
        repo.initialize()
        print(f"Initialized database at {repo.database_path}")
        return 0

    if args.discover:
        repo.initialize()
        taxonomy = RoleTaxonomy.from_yaml(args.taxonomy)
        companies = load_company_registry(args.companies)
        summary = DiscoveryPipeline(repo, taxonomy).run(companies)
        print(
            "Discovery summary: "
            f"companies={summary.companies_seen}, raw_jobs={summary.raw_jobs_seen}, "
            f"normalized={summary.normalized_jobs}, new_or_updated={summary.new_or_updated_jobs}, "
            f"eligible={summary.eligible_jobs}, skipped={summary.skipped_jobs}, "
            f"applications_created={summary.applications_created}, errors={len(summary.errors)}"
        )
        return 1 if summary.errors else 0

    if args.queue_eligible:
        repo.initialize()
        result = ApplicationQueue(repo).enqueue_eligible(args.limit)
        print(f"Queue result: queued={result.queued}, human_required={result.human_required}")
        return 0

    if args.daily_report:
        repo.initialize()
        report = build_daily_report(
            repo,
            date.today(),
            int(settings.get("target_verified_submissions_per_day", 100)),
            settings.get("timezone", "America/Los_Angeles"),
        )
        print(report.to_markdown())
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
