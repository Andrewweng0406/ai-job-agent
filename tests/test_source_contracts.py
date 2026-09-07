"""Job-source contract tests.

Validates the *normalized* `Job` contract each ATS adapter must satisfy:
external ID, canonical/source URL, title, company, location, description, posted date,
apply URL, and downstream dedupe behavior.

- Greenhouse / Lever / Ashby: run against Codex's real adapters in app/discovery/adapters.py.
- SmartRecruiters / Workday: adapters not implemented yet -> xfail, documenting the target contract
  so Codex can build to it. Fixtures live in tests/fixtures/ats/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.discovery.adapters import AshbyJobSource, GreenhouseJobSource, LeverJobSource
from app.matching.taxonomy import RoleTaxonomy
from app.models.company_registry import CompanyRegistryEntry
from app.models.job import Job
from app.normalization.deduplication import is_duplicate, job_identity_keys

FIXTURES = Path(__file__).parent / "fixtures" / "ats"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


class RoutingHttp:
    """Returns a fixed list payload for any list URL, and a detail payload for /jobs/<id>."""

    def __init__(self, list_payload, detail_payload=None):
        self.list_payload = list_payload
        self.detail_payload = detail_payload
        self.urls: list[str] = []

    def get_json(self, url: str):
        self.urls.append(url)
        if self.detail_payload is not None and "/jobs/" in url and not url.rstrip("/").endswith("jobs"):
            return self.detail_payload
        return self.list_payload


def taxonomy() -> RoleTaxonomy:
    return RoleTaxonomy(
        {
            "DATA_ANALYTICS": {"persona": "DATA", "title_keywords": ["data analyst"]},
            "PRODUCT_PM": {"persona": "PRODUCT_PM", "title_keywords": ["associate product manager"]},
            "BUSINESS_SYSTEMS": {"persona": "BUSINESS_SYSTEMS", "title_keywords": ["business analyst", "technology analyst"]},
            "FINANCE": {"persona": "FINANCE", "title_keywords": ["financial analyst"]},
        }
    )


def company(ats_type: str) -> CompanyRegistryEntry:
    return CompanyRegistryEntry(
        company_id="acmeco",
        company_name="Acme Co",
        career_url="https://example.test/careers",
        ats_type=ats_type,
        ats_identifier="acmeco",
    )


# --- contract assertion --------------------------------------------------------
REQUIRED_STR_FIELDS = ["external_job_id", "title", "company_name", "location", "description", "source_url", "apply_url"]


def assert_job_contract(job: Job, *, source: str) -> None:
    assert isinstance(job, Job)
    for field_name in REQUIRED_STR_FIELDS:
        value = getattr(job, field_name)
        assert isinstance(value, str) and value.strip(), f"{source}: {field_name} must be a non-empty string, got {value!r}"
    assert job.source == source
    assert job.ats_type == source
    assert job.company_name == "Acme Co"
    assert job.apply_url.startswith("http"), f"{source}: apply_url must be absolute"
    assert job.source_url.startswith("http"), f"{source}: source_url must be absolute"
    # normalized_title + description_hash are auto-populated
    assert job.normalized_title
    assert job.description_hash
    # identity keys must at least include the source+external id key
    keys = job_identity_keys(job)
    assert f"external:{source}:{job.external_job_id}" in keys


# --- Greenhouse --------------------------------------------------------------
def test_greenhouse_contract_and_fields():
    src = GreenhouseJobSource(company("greenhouse"), taxonomy(), RoutingHttp(load("greenhouse_list.json")))
    jobs = [src.normalize_job(raw) for raw in src.discover_jobs()]
    assert len(jobs) == 2
    grad = next(j for j in jobs if j.external_job_id == "6087345002")
    assert_job_contract(grad, source="greenhouse")
    assert grad.title.startswith("Data Analyst")
    assert grad.location == "New York, NY"
    assert "requirements" in grad.description.lower()
    assert grad.apply_url == "https://boards.greenhouse.io/acmeco/jobs/6087345002"
    # Greenhouse stable grouping id should be retained for near-dedupe
    assert grad.metadata.get("internal_job_id") == 5501230002


def test_greenhouse_posted_date_is_captured_or_flagged():
    src = GreenhouseJobSource(company("greenhouse"), taxonomy(), RoutingHttp(load("greenhouse_list.json")))
    grad = src.normalize_job(next(r for r in src.discover_jobs() if r["id"] == 6087345002))
    # CONTRACT: posted_at should reflect the fixture's updated_at (2026-08-30). Currently hard-coded None.
    if grad.posted_at is None:
        pytest.xfail("CLAUDE_REVIEW P2/P1-9: Greenhouse adapter discards updated_at; posted_at stays None")
    assert grad.posted_at.year == 2026


# --- Lever -----------------------------------------------------------------
def test_lever_contract_and_fields():
    src = LeverJobSource(company("lever"), taxonomy(), RoutingHttp(load("lever_list.json")))
    jobs = [src.normalize_job(raw) for raw in src.discover_jobs()]
    assert len(jobs) == 2
    ba = next(j for j in jobs if j.title.startswith("Business Analyst"))
    assert_job_contract(ba, source="lever")
    assert ba.external_job_id == "b1f9c3a2-7e2d-4c8a-9f10-2a4b6c8d0e12"
    assert ba.location == "San Francisco, CA"
    assert ba.employment_type == "FULL_TIME"
    assert ba.apply_url.endswith("/apply")


def test_lever_posted_date_from_created_at():
    src = LeverJobSource(company("lever"), taxonomy(), RoutingHttp(load("lever_list.json")))
    ba = src.normalize_job(next(r for r in src.discover_jobs() if r["text"].startswith("Business Analyst")))
    if ba.posted_at is None:
        pytest.xfail("CLAUDE_REVIEW P1-9: Lever adapter keeps createdAt only in metadata, not posted_at")
    assert ba.posted_at.year == 2026


# --- Ashby ---------------------------------------------------------------
def test_ashby_contract_and_fields():
    src = AshbyJobSource(company("ashby"), taxonomy(), RoutingHttp(load("ashby_list.json")))
    jobs = [src.normalize_job(raw) for raw in src.discover_jobs()]
    assert len(jobs) == 2
    apm = next(j for j in jobs if j.title.startswith("Associate Product Manager"))
    assert_job_contract(apm, source="ashby")
    assert apm.location in {"Remote, US", "Remote"}
    assert apm.salary_min == 110000 and apm.salary_max == 130000
    assert apm.currency == "USD"
    assert apm.metadata.get("published_at") == "2026-08-25T14:00:00.000Z"


def test_ashby_posted_date_from_published_at():
    src = AshbyJobSource(company("ashby"), taxonomy(), RoutingHttp(load("ashby_list.json")))
    apm = src.normalize_job(next(r for r in src.discover_jobs() if r["title"].startswith("Associate")))
    if apm.posted_at is None:
        pytest.xfail("CLAUDE_REVIEW P1-9: Ashby adapter keeps publishedAt only in metadata, not posted_at")
    assert apm.posted_at.year == 2026


# --- dedupe behavior across the normalized outputs ------------------------
def test_same_requisition_from_two_sources_dedupes_by_req_id():
    gh = GreenhouseJobSource(company("greenhouse"), taxonomy(), RoutingHttp(load("greenhouse_list.json")))
    gh_job = gh.normalize_job(next(r for r in gh.discover_jobs() if r["id"] == 6087345002))
    # Simulate the same requisition surfaced from a company-site mirror with a different tracking URL.
    mirror = Job(
        external_job_id="mirror-6087345002",
        company_id="acmeco",
        company_name="Acme Co, Inc.",
        title="Data Analyst, Growth",
        location="New York",
        description=gh_job.description + "  (mirrored listing, viewed 12 times)",
        source="company_site",
        source_url="https://careers.acme.test/jobs/6087345002",
        apply_url="https://boards.greenhouse.io/acmeco/jobs/6087345002?gh_src=abcdef&utm_campaign=x",
        ats_type="company_site",
    )
    assert is_duplicate(mirror, job_identity_keys(gh_job)), "req-id / canonical-URL dedupe should catch cross-source dupes"


def test_tracking_url_variants_dedupe():
    src = LeverJobSource(company("lever"), taxonomy(), RoutingHttp(load("lever_list.json")))
    base = src.normalize_job(next(r for r in src.discover_jobs() if r["text"].startswith("Business Analyst")))
    tracked = Job(
        external_job_id=base.external_job_id,
        company_id="acmeco",
        company_name="Acme Co",
        title=base.title,
        location=base.location,
        description=base.description,
        source="lever",
        source_url=base.source_url,
        apply_url=base.apply_url + "?lever-source=LinkedIn&utm_medium=social",
        ats_type="lever",
    )
    assert is_duplicate(tracked, job_identity_keys(base))


def test_smartrecruiters_contract():
    from app.discovery.adapters import SmartRecruitersJobSource  # type: ignore

    src = SmartRecruitersJobSource(company("smartrecruiters"), taxonomy(), RoutingHttp(load("smartrecruiters_list.json")))
    jobs = [src.normalize_job(raw) for raw in src.discover_jobs()]
    fa = next(j for j in jobs if j.title.startswith("Financial Analyst"))
    assert_job_contract(fa, source="smartrecruiters")
    assert fa.external_job_id == "743999912345678"
    assert fa.location.startswith("Chicago")
    assert fa.posted_at is not None and fa.posted_at.year == 2026
    assert fa.apply_url.startswith("https://jobs.smartrecruiters.com/AcmeCo/")


def test_workday_contract():
    from app.discovery.adapters import WorkdayJobSource  # type: ignore

    http = RoutingHttp(load("workday_list.json"), detail_payload=load("workday_detail.json"))
    src = WorkdayJobSource(company("workday"), taxonomy(), http)
    jobs = [src.normalize_job(raw) for raw in src.discover_jobs()]
    ta = next(j for j in jobs if j.title.startswith("Technology Analyst"))
    assert_job_contract(ta, source="workday")
    assert ta.external_job_id == "R-2026-11045"  # jobRequisitionId, not externalPath
    assert ta.posted_at is not None and ta.posted_at.year == 2026
    assert ta.apply_url.startswith("https://acme.wd5.myworkdayjobs.com/")
