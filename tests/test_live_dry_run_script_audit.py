"""Audit of scripts/live_dry_run.py — the tool that actually produces the evidence bundles.

Codex hardened GreenhouseLiveDryRunRunner (lease fencing at 5 points + per-field lease_check +
post-fill hard-stop re-scan + approved_transcript_id gate). But the evidence-producing SCRIPT
reimplements the flow inline and does NOT go through that runner, so several protections are absent
from the path that will generate the Gate-G approved-autofill bundle.

Passing = a property that holds. xfail(strict=False) = a gap (CLAUDE_REVIEW P1-29 / P1-30 / P1-31 / P2-31).
"""
from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" / "live_dry_run.py").read_text()


# ---------------------------------------------------------------- properties that hold
def test_script_refuses_real_submission():
    assert 'raise SystemExit("real_submission_enabled must remain false")' in SCRIPT


def test_script_never_calls_a_submit_primitive():
    for banned in ('press("Enter")', "press('Enter')", "requestSubmit", "form.submit(",
                   ".submit()", 'click("[type=submit]', "keyboard.press", "dispatchEvent"):
        assert banned not in SCRIPT, f"script contains a submit primitive: {banned}"


def test_script_gates_autofill_behind_approval_builder():
    assert "ApprovedAutofillPreviewBuilder(repo).build(transcript.transcript_id)" in SCRIPT
    assert "if args.approved_by" in SCRIPT


def test_script_writes_a_blocked_bundle_on_hard_stop():
    assert "_write_blocked_bundle(" in SCRIPT
    assert '"hard_stop": True' in SCRIPT


# ---------------------------------------------------------------- gaps

@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-29: the script calls DryRunBrowserAutofill().apply() with NO lease_check= — the per-field lease fencing (P1-28c) is bypassed in the evidence path")
def test_script_autofill_passes_a_lease_check_callback():
    assert "DryRunBrowserAutofill().apply(" in SCRIPT
    call = SCRIPT.split("DryRunBrowserAutofill().apply(", 1)[1].split(")", 1)[0]
    assert "lease_check" in call


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-30: the script never calls lease_still_mine after the initial claim — no lease fencing around nav / capture / autofill / screenshot")
def test_script_fences_the_lease_during_browser_work():
    assert SCRIPT.count("lease_still_mine") >= 1 or SCRIPT.count("_assert_lease") >= 1


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-30b: POST_FILL_SCAN action is logged but nothing is re-captured/checked — no post-fill bot-wall detection in the evidence path")
def test_script_actually_rescans_for_a_bot_wall_after_autofill():
    tail = SCRIPT.split('"POST_FILL_SCAN"', 1)[0][-600:]
    assert "capture(" in tail or "human_required" in tail or "persist_browser_hard_stop" in tail


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P1-31: safety.json hardcodes attempted_field_count/matched_field_count/mismatch_count = 0 even when autofill ran — the transcript<->browser differential is a fabricated zero")
def test_safety_json_reflects_the_real_autofill_differential():
    seg = SCRIPT.split('"safety.json"', 1)[1].split("}", 1)[0]
    assert '"attempted_field_count": 0' not in seg, "safety.json hardcodes attempted_field_count=0"
    assert '"mismatch_count": 0' not in seg or "mismatch" in SCRIPT.split("autofill.apply", 1)[-1][:800]


@pytest.mark.xfail(strict=False, reason="CLAUDE_REVIEW P2-31: no separation/marking between a real config profile and a synthetic test profile; a test profile with plausible data could drive live autofill")
def test_candidate_profile_distinguishes_synthetic_from_real():
    from app.resumes.profile import CandidateProfile

    src = __import__("inspect").getsource(CandidateProfile)
    assert "synthetic" in src.lower() or "test_only" in src.lower() or "profile_source" in src.lower()
