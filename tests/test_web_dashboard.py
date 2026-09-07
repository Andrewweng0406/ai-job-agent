from app.web_dashboard import DASHBOARD_HTML


def test_dashboard_has_review_surfaces_and_no_submit_control():
    assert "Refresh job search" in DASHBOARD_HTML
    assert "Human review queue" in DASHBOARD_HTML
    assert "Submission is permanently disabled" in DASHBOARD_HTML
    assert "submit" not in DASHBOARD_HTML.lower().replace("submission is permanently disabled", "")
