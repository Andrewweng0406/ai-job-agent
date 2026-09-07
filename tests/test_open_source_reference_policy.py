from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_open_source_comparison_records_safe_adaptation_policy() -> None:
    comparison = (ROOT / "docs" / "OPEN_SOURCE_REFERENCE_COMPARISON.md").read_text()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()

    for repo in ("CareerWeaver", "applyai", "ai-job-agent"):
        assert repo in comparison
        assert repo in notices
    assert "No source copied" in comparison
    assert "real_submission_enabled=false" in comparison
    assert "SUBMISSION_UNKNOWN" in comparison
    assert "MIT" in notices
