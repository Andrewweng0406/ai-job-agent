import inspect

from app.web_dashboard import DASHBOARD_HTML, DashboardHandler


def test_dashboard_has_the_core_surfaces():
    for needle in ("Search jobs", "Human review queue", "AI cost control", "candidate PII",
                   "Queue eligible", "New review packet", "Review packets", "Batch review",
                   "submission is permanently disabled"):
        assert needle in DASHBOARD_HTML, needle


def test_dashboard_has_no_submitting_route():
    src = inspect.getsource(DashboardHandler)
    # the POST routes it serves
    assert "/api/packet/create" in src and "/api/packet/answers" in src and "/api/packet/fill" in src
    assert "/api/batch/prepare" in src and "/api/batch/approve" in src
    # nothing that submits an application
    for banned in ("real_submission_enabled=True", "/api/submit", "def do_PUT", "requestSubmit"):
        assert banned not in src, banned
    # state always reports submission disabled
    assert '"real_submission_enabled": False' in src


def test_batch_routes_run_no_submit_scripts_and_guard_paths():
    src = inspect.getsource(DashboardHandler)
    assert "scripts/batch_prepare.py" in src
    assert "scripts/batch_fill.py" in src
    # approve refuses a blocked record
    assert 'get("blocked")' in inspect.getsource(DashboardHandler._batch_approve)
    assert "load_batch_answers" in inspect.getsource(DashboardHandler._batch_approve)
    # screenshot + item routes are path-traversal guarded via _safe_batch_dir
    assert "_safe_batch_dir" in inspect.getsource(DashboardHandler._batch_detail)
    assert "_safe_batch_dir" in inspect.getsource(DashboardHandler._batch_screenshot)


def test_batch_ui_disables_fill_for_unready_records_and_hides_missing_images():
    assert "bApprove.disabled=!(rec.ready||x.approval_valid)" in DASHBOARD_HTML
    assert "bShot.style.display='none'" in DASHBOARD_HTML
    assert "button:disabled" in DASHBOARD_HTML
    assert "Open application website" in DASHBOARD_HTML
    assert "rel=\"noopener noreferrer\"" in DASHBOARD_HTML
    assert "Required coverage" in DASHBOARD_HTML
    assert "required_resolved" in DASHBOARD_HTML
    assert "/api/batch/answers" in inspect.getsource(DashboardHandler)
    assert "record_hash" in DASHBOARD_HTML


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
