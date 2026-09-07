from app.discovery.pipeline import DiscoveryPipeline
from app.matching.taxonomy import RoleTaxonomy
from app.models.company_registry import CompanyRegistryEntry
from app.models.job import Job
from app.database.repository import JobAgentRepository


class FakeSource:
    source_name = "fixture"

    def discover_jobs(self):
        return [{"id": "1", "title": "Data Analyst"}]

    def fetch_job(self, external_job_id):
        return {"id": external_job_id, "title": "Data Analyst"}

    def normalize_job(self, raw_job):
        return Job(
            external_job_id=raw_job["id"],
            company_id="acme",
            company_name="Acme",
            title=raw_job["title"],
            location="Remote",
            description="Entry-level SQL role.",
            source="fixture",
            source_url="https://example.test/job",
            apply_url="https://example.test/apply",
            ats_type="fixture",
            job_family=RoleTaxonomy({"DATA_ANALYTICS": {"title_keywords": ["data analyst"]}}).classify_title(raw_job["title"]),
        )


def test_discovery_pipeline_creates_application_once(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    taxonomy = RoleTaxonomy({"DATA_ANALYTICS": {"title_keywords": ["data analyst"]}})
    company = CompanyRegistryEntry("acme", "Acme", "https://example.test/careers", "fixture", "acme")
    pipeline = DiscoveryPipeline(repo, taxonomy, source_factory=lambda _company, _taxonomy: FakeSource())

    first = pipeline.run([company])
    second = pipeline.run([company])

    assert first.applications_created == 1
    assert second.applications_created == 0
    with repo.connect() as conn:
        applications = conn.execute("SELECT COUNT(*) AS count FROM applications").fetchone()
        filters = conn.execute("SELECT COUNT(*) AS count FROM job_filter_results").fetchone()
        transitions = conn.execute("SELECT COUNT(*) AS count FROM application_state_transitions").fetchone()
    assert applications["count"] == 1
    assert filters["count"] == 1
    assert transitions["count"] == 1


class NoSponsorshipSource(FakeSource):
    def normalize_job(self, raw_job):
        job = super().normalize_job(raw_job)
        job.description = "Candidates must be authorized to work in the U.S. without sponsorship."
        return job


def test_discovery_pipeline_marks_work_auth_unknown_as_human_required(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    taxonomy = RoleTaxonomy({"DATA_ANALYTICS": {"title_keywords": ["data analyst"]}})
    company = CompanyRegistryEntry("acme", "Acme", "https://example.test/careers", "fixture", "acme")
    pipeline = DiscoveryPipeline(
        repo,
        taxonomy,
        source_factory=lambda _company, _taxonomy: NoSponsorshipSource(),
        requires_visa_sponsorship=None,
    )

    summary = pipeline.run([company])

    assert summary.applications_created == 0
    with repo.connect() as conn:
        row = conn.execute("SELECT status, human_required_reason FROM applications").fetchone()
    assert row["status"] == "HUMAN_REQUIRED"
    assert row["human_required_reason"] == "WORK_AUTHORIZATION_PROFILE_INCOMPLETE"


class SameRequisitionSource:
    source_name = "fixture"

    def discover_jobs(self):
        return [
            {"id": "post-1", "url": "https://example.test/apply/1", "title": "Data Analyst", "location": "Remote", "description": "Entry-level SQL role."},
            {"id": "post-2", "url": "https://example.test/apply/2", "title": "Analytics Analyst", "location": "New York, NY", "description": "Entry-level dashboard role."},
        ]

    def fetch_job(self, external_job_id):
        return {"id": external_job_id}

    def normalize_job(self, raw_job):
        return Job(
            external_job_id=raw_job["id"],
            company_id="acme",
            company_name="Acme",
            title=raw_job["title"],
            location=raw_job["location"],
            description=raw_job["description"],
            source="fixture",
            source_url=raw_job["url"],
            apply_url=raw_job["url"],
            ats_type="fixture",
            job_family=RoleTaxonomy({"DATA_ANALYTICS": {"title_keywords": ["data analyst", "analytics analyst"]}}).classify_title(raw_job["title"]),
            metadata={"requisition_id": "REQ-1"},
        )


def test_discovery_pipeline_dedupe_key_prevents_second_application_for_same_requisition(tmp_path):
    repo = JobAgentRepository(tmp_path / "agent.sqlite3")
    repo.initialize()
    taxonomy = RoleTaxonomy({"DATA_ANALYTICS": {"title_keywords": ["data analyst"]}})
    company = CompanyRegistryEntry("acme", "Acme", "https://example.test/careers", "fixture", "acme")
    pipeline = DiscoveryPipeline(repo, taxonomy, source_factory=lambda _company, _taxonomy: SameRequisitionSource())

    summary = pipeline.run([company])

    with repo.connect() as conn:
        applications = conn.execute("SELECT COUNT(*) AS count FROM applications").fetchone()
        transitions = conn.execute("SELECT COUNT(*) AS count FROM application_state_transitions WHERE to_status = 'ELIGIBLE'").fetchone()
    assert summary.eligible_jobs == 2
    assert summary.applications_created == 1
    assert applications["count"] == 1
    assert transitions["count"] == 1
