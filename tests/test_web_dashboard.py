import inspect

from app.web_dashboard import DASHBOARD_HTML, DashboardHandler


def test_dashboard_has_the_core_surfaces():
    for needle in ("Search jobs", "Human review queue", "AI cost control", "candidate PII",
                   "Queue eligible", "New review packet", "Review packets",
                   "submission is permanently disabled"):
        assert needle in DASHBOARD_HTML, needle


def test_dashboard_has_no_submitting_route():
    src = inspect.getsource(DashboardHandler)
    # the POST routes it serves
    assert "/api/packet/create" in src and "/api/packet/answers" in src and "/api/packet/fill" in src
    # nothing that submits an application
    for banned in ("real_submission_enabled=True", "/api/submit", "def do_PUT", "requestSubmit"):
        assert banned not in src, banned
    # state always reports submission disabled
    assert '"real_submission_enabled": False' in src


def test_assisted_fill_route_launches_the_no_submit_script_headed():
    src = inspect.getsource(DashboardHandler._packet_fill)
    assert "assisted_apply.py" in src and "fill" in src and "--headed" in src
    assert "answers.yaml" in src  # refuses without approved answers


def test_packet_dir_is_path_traversal_guarded():
    h = DashboardHandler.__new__(DashboardHandler)
    h.review_root = __import__("pathlib").Path("review")
    assert h._safe_dir("../etc") is None
    assert h._safe_dir("a/b") is None
    assert h._safe_dir("ok-slug_1.2") is not None
