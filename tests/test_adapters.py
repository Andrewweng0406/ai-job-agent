from app.discovery.adapters import AshbyJobSource, GreenhouseJobSource, LeverJobSource
from app.matching.taxonomy import RoleTaxonomy
from app.models.company_registry import CompanyRegistryEntry
from app.models.enums import JobFamily


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return self.payload


def taxonomy():
    return RoleTaxonomy({"DATA_ANALYTICS": {"title_keywords": ["data analyst"]}})


def company(ats_type="greenhouse"):
    return CompanyRegistryEntry(
        company_id="acme",
        company_name="Acme",
        career_url="https://example.test/careers",
        ats_type=ats_type,
        ats_identifier="acme",
    )


def test_greenhouse_normalizes_job():
    source = GreenhouseJobSource(
        company(),
        taxonomy(),
        FakeHttp({"jobs": [{"id": 1, "title": "Data Analyst", "location": {"name": "Remote"}, "content": "<p>SQL</p>", "absolute_url": "https://example.test/1"}]}),
    )
    job = source.normalize_job(source.discover_jobs()[0])
    assert job.external_job_id == "1"
    assert job.description == "SQL"
    assert job.job_family == JobFamily.DATA_ANALYTICS


def test_lever_accepts_array_payload():
    source = LeverJobSource(
        company("lever"),
        taxonomy(),
        FakeHttp([{"id": "abc", "text": "Data Analyst", "categories": {"location": "NYC", "commitment": "Full-time"}, "descriptionPlain": "SQL"}]),
    )
    job = source.normalize_job(source.discover_jobs()[0])
    assert job.employment_type == "FULL_TIME"


def test_ashby_extracts_salary():
    payload = {
        "jobs": [
            {
                "id": "abc",
                "title": "Data Analyst",
                "location": "Remote",
                "descriptionPlain": "SQL",
                "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
                "applyUrl": "https://jobs.ashbyhq.com/acme/abc/application",
                "employmentType": "FullTime",
                "compensation": {
                    "summaryComponents": [
                        {"compensationType": "Salary", "currencyCode": "USD", "minValue": 80000, "maxValue": 90000}
                    ]
                },
            }
        ]
    }
    source = AshbyJobSource(company("ashby"), taxonomy(), FakeHttp(payload))
    job = source.normalize_job(source.discover_jobs()[0])
    assert job.salary_min == 80000
    assert job.salary_max == 90000

