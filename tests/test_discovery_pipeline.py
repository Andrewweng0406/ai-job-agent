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

