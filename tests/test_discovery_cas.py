"""Discovery / application-creation CAS race verification (WS1-B, CLAUDE_REVIEW P1-14).

Multiple discovery workers see the same job at the same time. Expected:
  ONE canonical jobs row, ONE canonical applications row, no unhandled RuntimeError,
  and the same requisition arriving via 4 different URL shapes converges to one application.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.database.repository import JobAgentRepository
from app.discovery.pipeline import DiscoveryPipeline
from app.matching.taxonomy import RoleTaxonomy
from app.models.company_registry import CompanyRegistryEntry
from app.models.job import Job


TAXO = RoleTaxonomy({"DATA_ANALYTICS": {"persona": "DATA", "title_keywords": ["data analyst"]}})


def _company():
    return CompanyRegistryEntry(
        company_id="acmeco", company_name="Acme Co", career_url="https://careers.acme.test",
        ats_type="greenhouse", ats_identifier="acmeco",
    )


class _FixedSource:
    """A JobSource that always yields the same one requisition, optionally via a given apply_url."""

    source_name = "greenhouse"

    def __init__(self, company, taxonomy, apply_url=None, source="greenhouse", ext="gh-555"):
        self.company = company
        self._apply_url = apply_url or "https://boards.greenhouse.io/acmeco/jobs/555"
        self._source = source
        self._ext = ext

    def discover_jobs(self):
        return [{"id": self._ext}]

    def fetch_job(self, external_job_id):
        return {"id": external_job_id}

    def normalize_job(self, raw):
        return Job(
            external_job_id=str(raw["id"]), company_id="acmeco", company_name="Acme Co",
            title="Data Analyst", location="New York, NY",
            description="Analytics team. Requisition R-555. Build dashboards with SQL.",
            source=self._source, source_url=self._apply_url, apply_url=self._apply_url,
            ats_type=self._source,
        )


def _repo(tmp_path):
    r = JobAgentRepository(tmp_path / "cas.sqlite3")
    r.initialize()
    return r


@pytest.mark.parametrize("concurrency", [2, 4, 8])
def test_concurrent_discovery_creates_one_job_one_application(tmp_path, concurrency):
    repo = _repo(tmp_path)

    def run_once(_):
        pipeline = DiscoveryPipeline(repo, TAXO, source_factory=lambda c, t: _FixedSource(c, t))
        return pipeline.run([_company()])

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        summaries = list(ex.map(run_once, range(concurrency)))

    for s in summaries:
        assert s.errors == [], f"unhandled pipeline error at concurrency {concurrency}: {s.errors}"

    with repo.connect() as conn:
        jobs = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        apps = conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
        elig_transitions = conn.execute(
            "SELECT COUNT(*) c FROM application_state_transitions WHERE to_status='ELIGIBLE'"
        ).fetchone()["c"]
    assert jobs == 1, f"{jobs} job rows"
    assert apps == 1, f"{apps} application rows"
    assert elig_transitions <= 1, f"{elig_transitions} ELIGIBLE transitions for one application"


def test_same_greenhouse_requisition_via_tracking_url_variants_converges(tmp_path):
    """The same Greenhouse posting (source=greenhouse, external_job_id=555) reached through
    4 different apply-URL shapes (canonical, ?gh_src, ?utm, trailing slash) must stay ONE job
    and ONE application across separate discovery runs."""
    repo = _repo(tmp_path)
    url_variants = [
        "https://boards.greenhouse.io/acmeco/jobs/555",
        "https://boards.greenhouse.io/acmeco/jobs/555?gh_src=abcd&utm_source=google",
        "https://boards.greenhouse.io/acmeco/jobs/555?ref=simplify",
        "https://boards.greenhouse.io/acmeco/jobs/555/",
    ]
    for url in url_variants:
        pipeline = DiscoveryPipeline(
            repo, TAXO,
            source_factory=lambda c, t, u=url: _FixedSource(c, t, apply_url=u, source="greenhouse", ext="555"),
        )
        summary = pipeline.run([_company()])
        assert summary.errors == []

    with repo.connect() as conn:
        jobs = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        apps = conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
    assert jobs == 1, f"{jobs} job rows for one requisition"
    assert apps == 1, "the same requisition via tracking-URL variants must converge to one application"


def test_same_requisition_via_different_source_labels_converges(tmp_path):
    repo = _repo(tmp_path)
    for source, ext in [("greenhouse", "gh-555"), ("company_site", "acme-555"), ("aggregator", "agg-9")]:
        pipeline = DiscoveryPipeline(
            repo, TAXO,
            source_factory=lambda c, t, s=source, e=ext: _FixedSource(
                c, t, apply_url="https://boards.greenhouse.io/acmeco/jobs/555", source=s, ext=e
            ),
        )
        pipeline.run([_company()])
    with repo.connect() as conn:
        apps = conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
    assert apps == 1
