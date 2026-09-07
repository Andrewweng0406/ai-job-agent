from app.web_dashboard import DASHBOARD_HTML


def test_dashboard_has_review_surfaces_and_no_submit_control():
    assert "Search jobs" in DASHBOARD_HTML
    assert "Human review queue" in DASHBOARD_HTML
    assert "AI cost control" in DASHBOARD_HTML
    assert "candidate PII" in DASHBOARD_HTML
    assert "Queue eligible" in DASHBOARD_HTML
    assert "Build dry-run" in DASHBOARD_HTML
    assert "Submission is permanently disabled" in DASHBOARD_HTML
    assert "submit" not in DASHBOARD_HTML.lower().replace("submission is permanently disabled", "")
