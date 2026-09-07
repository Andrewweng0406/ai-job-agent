import json
from pathlib import Path


def test_committed_live_evidence_bundle_has_required_files():
    bundle = Path("artifacts/phase43-anthropic-4461450008-v5")
    required = {
        "report.json", "dom.sanitized.html", "field_map.json", "browser_actions.jsonl",
        "safety.json", "transcript.sanitized.json", "before_fill.png", "after_fill.png",
    }
    assert {path.name for path in bundle.iterdir()} >= required
    report = json.loads((bundle / "report.json").read_text())
    safety = json.loads((bundle / "safety.json").read_text())
    assert report["live_page"] is True
    assert report["real_browser"] is True
    assert report["submit_invocation_count"] == 0
    assert report["would_submit"] is False
    assert safety["mismatch_count"] == 0
    assert safety["unplanned_browser_actions"] == 0


def test_live_evidence_field_map_is_dom_traceable():
    bundle = Path("artifacts/phase43-anthropic-4461450008-v5")
    html = (bundle / "dom.sanitized.html").read_text()
    fields = json.loads((bundle / "field_map.json").read_text())
    assert fields
    assert all(field["hidden"] is False for field in fields)
    assert all(field["element_tag"] in {"input", "select", "textarea", "text", "select", "long_text"} for field in fields)
    assert all(field["raw_label"] for field in fields)


def test_live_evidence_action_log_contains_no_submit_action():
    actions = Path("artifacts/phase43-anthropic-4461450008-v5/browser_actions.jsonl").read_text()
    assert not any(token in actions for token in ("PRESS_ENTER", "SUBMIT", "REQUEST_SUBMIT", "FORM_SUBMIT", "CLICK_SUBMIT"))
