from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "live_dry_run.py"
    spec = spec_from_file_location("live_dry_run_under_test", path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_sanitized_transcript_redacts_every_candidate_field_value():
    sanitize = _script_module()._sanitize_payload
    payload = {
        "fields": [
            {"canonical_key": "name.full", "value": "Test Candidate"},
            {"canonical_key": "address.street", "value": "1 Main Street"},
            {"canonical_key": "links.linkedin", "value": "https://example.test/person"},
            {"canonical_key": "custom_answer", "value": "private free text"},
            {"canonical_key": "optional", "value": None},
        ]
    }
    clean = sanitize(payload)
    assert [field["value"] for field in clean["fields"]] == [
        "[REDACTED]", "[REDACTED]", "[REDACTED]", "[REDACTED]", None
    ]
    assert payload["fields"][0]["value"] == "Test Candidate"


def test_live_page_title_controls_evidence_role():
    parse_role = _script_module()._role_from_page_title
    assert parse_role(
        "Job Application for Account Executive, AI Native at Anthropic",
        "Wrong CLI Role",
    ) == "Account Executive, AI Native"
    assert parse_role("Careers", "CLI Fallback") == "CLI Fallback"


def test_approved_url_comparison_ignores_only_query_and_trailing_slash():
    canonical = _script_module()._canonical_url
    assert canonical("https://EXAMPLE.test/jobs/1/?source=x") == "https://example.test/jobs/1"
    assert canonical("https://example.test/jobs/2") != canonical("https://example.test/jobs/1")
