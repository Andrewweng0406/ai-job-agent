from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path


def _resolve_candidate_profile(requested: str | None) -> str:
    """Real candidate facts must never live in a tracked file. When no path is given, prefer the
    gitignored `config/candidate_profile.local.yaml`; otherwise fall back to the tracked template.
    An explicit `--candidate-profile PATH` is always honored verbatim.
    """
    if requested is not None:
        return requested
    local = Path("config/candidate_profile.local.yaml")
    return str(local) if local.exists() else "config/candidate_profile.yaml"

from app.database.repository import JobAgentRepository
from app.discovery.pipeline import DiscoveryPipeline
from app.matching.taxonomy import RoleTaxonomy
from app.applications.queue import ApplicationQueue
from app.models.enums import ApplicationStatus
from app.reporting.daily_report import build_daily_report
from app.resumes.profile import CandidateProfile, profile_completeness_gate
from app.services.company_registry import load_company_registry
from app.services.application_preparer import ApplicationPreparer
from app.services.dry_run_preparer import ApplicationDryRunPreparer
from app.applications.preview import ApprovedAutofillPreviewBuilder
from app.llm.tailoring import TailoringMode
from app.llm.runtime import runtime_status
from app.utils.config import load_yaml
from app.utils.logging import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous new-grad job application agent.")
    parser.add_argument("--init-db", action="store_true", help="Initialize the local SQLite database schema.")
    parser.add_argument("--discover", action="store_true", help="Run read-only job discovery for configured companies.")
    parser.add_argument("--company-id", help="Limit discovery to one company_id from the registry.")
    parser.add_argument("--show-new-jobs", action="store_true", help="Show recently discovered NEW jobs.")
    parser.add_argument("--show-eligible-jobs", action="store_true", help="Show eligible/queued/ready applications.")
    parser.add_argument("--discovery-stats", action="store_true", help="Show discovery and filtering statistics.")
    parser.add_argument("--queue-eligible", action="store_true", help="Move eligible applications into the queue.")
    parser.add_argument("--daily-report", action="store_true", help="Print today's daily KPI report.")
    parser.add_argument("--check-profile", action="store_true", help="Validate required candidate profile facts.")
    parser.add_argument("--prepare-next", action="store_true", help="Tailor a resume, generate a PDF, and print a safe application preview for one queued application.")
    parser.add_argument("--dry-run-next", action="store_true", help="Build and persist a no-submit dry-run transcript for one ready application.")
    parser.add_argument("--autofill-preview", help="Render an approved, hash-valid dry-run transcript as an autofill preview.")
    parser.add_argument("--tailoring-mode", choices=["FAST", "DEEP"], default="FAST", help="Resume tailoring mode.")
    parser.add_argument("--llm-status", action="store_true", help="Show local LLM readiness without making an API request.")
    parser.add_argument("--limit", type=int, default=100, help="Limit for queueing operations.")
    parser.add_argument("--settings", default="config/settings.yaml", help="Path to settings YAML.")
    parser.add_argument("--companies", default="config/companies.yaml", help="Path to company registry YAML.")
    parser.add_argument("--taxonomy", default="config/role_taxonomy.yaml", help="Path to role taxonomy YAML.")
    parser.add_argument("--candidate-profile", default=None,
                        help="Path to candidate profile YAML (default: config/candidate_profile.local.yaml if present, else the tracked template).")
    args = parser.parse_args()
    args.candidate_profile = _resolve_candidate_profile(args.candidate_profile)

    configure_logging()
    settings = load_yaml(args.settings)
    repo = JobAgentRepository(settings.get("database_path", "data/job_agent.sqlite3"))

    if args.llm_status:
        status = runtime_status(settings)
        print(f"LLM enabled: {str(status.enabled).lower()}")
        print(f"Provider configured: {str(status.configured).lower()}")
        print(f"Provider: {status.provider}")
        print(f"Cheap model: {status.cheap_model}")
        print(f"Strong model: {status.strong_model}")
        print(f"Candidate PII allowed: {str(status.send_candidate_pii).lower()}")
        print(f"Status: {status.reason}")
        return 0 if status.reason == "READY" else 1

    if args.init_db:
        repo.initialize()
        print(f"Initialized database at {repo.database_path}")
        return 0

    if args.discover:
        repo.initialize()
        taxonomy = RoleTaxonomy.from_yaml(args.taxonomy)
        profile = CandidateProfile.from_yaml(args.candidate_profile)
        companies = load_company_registry(args.companies)
        if args.company_id:
            companies = [company for company in companies if company.company_id == args.company_id]
        summary = DiscoveryPipeline(
            repo,
            taxonomy,
            candidate_id=profile.candidate_id,
            requires_visa_sponsorship=profile.requires_future_sponsorship(),
        ).run(companies)
        print(
            "Discovery summary: "
            f"companies={summary.companies_seen}, raw_jobs={summary.raw_jobs_seen}, "
            f"normalized={summary.normalized_jobs}, new_or_updated={summary.new_or_updated_jobs}, "
            f"eligible={summary.eligible_jobs}, skipped={summary.skipped_jobs}, "
            f"applications_created={summary.applications_created}, errors={len(summary.errors)}"
        )
        return 1 if summary.errors else 0

    if args.show_new_jobs:
        repo.initialize()
        for row in repo.list_jobs_by_status("NEW", args.limit):
            print(f"{row['id']}\t{row['company_name']}\t{row['title']}\t{row['location']}\t{row['apply_url']}")
        return 0

    if args.show_eligible_jobs:
        repo.initialize()
        for row in repo.list_eligible_applications(args.limit):
            print(f"{row['application_id']}\t{row['status']}\t{row['company']}\t{row['position']}\t{row['location']}\t{row['apply_url']}")
        return 0

    if args.discovery_stats:
        repo.initialize()
        for key, value in sorted(repo.discovery_stats().items()):
            print(f"{key}: {value}")
        return 0

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

    if args.check_profile:
        profile = CandidateProfile.from_yaml(args.candidate_profile)
        result = profile_completeness_gate(profile)
        if result.complete:
            print("Candidate profile completeness: OK")
            return 0
        print("Candidate profile completeness: HUMAN_REQUIRED")
        for fact_id in result.missing_fact_ids:
            print(f"- Missing required fact: {fact_id}")
        return 1

    if args.prepare_next:
        repo.initialize()
        profile = CandidateProfile.from_yaml(args.candidate_profile)
        result = ApplicationPreparer(repo).prepare_next(profile, TailoringMode(args.tailoring_mode))
        if result.preview:
            print(result.preview.to_markdown())
            return 0
        print(f"Prepare result: status={result.status.value}, reason={result.reason}")
        return 1 if result.status == ApplicationStatus.HUMAN_REQUIRED else 0

    if args.dry_run_next:
        repo.initialize()
        profile = CandidateProfile.from_yaml(args.candidate_profile)
        result = ApplicationDryRunPreparer(repo).dry_run_next(profile)
        if result.dry_run is None:
            print(f"Dry-run result: status={result.status.value}, reason={result.reason}")
            return 1 if result.status == ApplicationStatus.HUMAN_REQUIRED else 0
        transcript = result.dry_run.transcript
        payload = transcript.payload
        print(f"Dry-run transcript: {transcript.transcript_id}")
        print(f"Application status: {result.status.value}")
        print(f"Would submit: {str(transcript.would_submit).lower()}")
        print(f"Blocking reasons: {', '.join(transcript.blocking_reasons) if transcript.blocking_reasons else 'none'}")
        print(f"Fields: {len(payload['fields'])}")
        print(f"Unresolved: {len(payload['unresolved'])}")
        return 0

    if args.autofill_preview:
        repo.initialize()
        try:
            print(ApprovedAutofillPreviewBuilder(repo).build(args.autofill_preview).to_markdown())
        except (KeyError, RuntimeError) as exc:
            print(f"Autofill preview unavailable: {exc}")
            return 1
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
