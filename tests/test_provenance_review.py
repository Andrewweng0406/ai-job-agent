"""Independent reviewer verification of the open-source reference / provenance claims (86c3b5e).

The three upstream repos in THIRD_PARTY_NOTICES.md were verified by the reviewer to exist and to be
MIT-licensed:
  - github.com/idea-torx/CareerWeaver   (Python, MIT)
  - github.com/muhammad-saadd/applyai   (JavaScript / Chrome extension, MIT)
  - github.com/AkbarDevop/ai-job-agent  (JS+Python, MIT)

These tests lock in the structural facts a reviewer can check offline: the reference commit added no
implementation code, the repo contains no JavaScript (the two JS references could not have been
code-copied), and the provenance/notice docs stay present with the "no code copied" commitment.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repo_contains_no_javascript_so_the_js_references_were_not_code_copied():
    js = [p for p in ROOT.rglob("*.js") if ".git" not in p.parts and "node_modules" not in p.parts]
    assert js == [], f"unexpected JavaScript files: {js}"
    mjs = [p for p in ROOT.rglob("*.mjs") if ".git" not in p.parts]
    assert mjs == [], f"unexpected .mjs files: {mjs}"


def test_reference_review_commit_added_no_implementation_code():
    out = subprocess.run(
        ["git", "show", "--stat", "--format=", "86c3b5e"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    assert out, "commit 86c3b5e not found"
    changed = [line.split("|")[0].strip() for line in out.splitlines() if "|" in line]
    for path in changed:
        assert not path.startswith("app/"), f"reference-review commit touched implementation file: {path}"


def test_third_party_notices_are_present_and_commit_to_updating_on_any_copy():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    for repo in ("CareerWeaver", "applyai", "ai-job-agent"):
        assert repo in notices
    assert "MIT" in notices
    assert "no upstream code is distributed" in notices.lower() or "no code copied" in notices
    # the governance promise: any future copy/adaptation must update the table before merge
    assert "before merging" in notices


def test_open_source_comparison_records_the_safety_posture():
    comparison = (ROOT / "docs" / "OPEN_SOURCE_REFERENCE_COMPARISON.md").read_text()
    assert "real_submission_enabled=false" in comparison
    assert "No upstream source file was incorporated" in comparison
    for repo in ("CareerWeaver", "applyai", "ai-job-agent"):
        assert repo in comparison
