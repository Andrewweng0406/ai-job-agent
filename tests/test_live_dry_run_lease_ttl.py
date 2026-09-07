"""Regressions in scripts/live_dry_run.py exposed after the lease-check hardening (931d78d).

- P1: the evidence run claims its lease with a 0-second TTL (`lease_expires_at = datetime.now()`),
  so every `_lease_check` after the first slow browser op fails -> LEASE_LOST -> blocked bundle.
  The tooling can no longer produce a passing transcript/autofill bundle.
- P1: a `--approved-by` run has NO URL allowlist / acknowledgment guard, so it will type the real
  candidate profile (name/email/phone from the gitignored .local.yaml) into whatever live employer
  form `--url` points at.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_dry_run.py"
SCRIPT = SCRIPT_PATH.read_text()


def test_evidence_lease_is_claimed_with_a_real_ttl():
    m = re.search(r"claim_next_application\([^)]*\)", SCRIPT)
    assert m, "no claim_next_application call found"
    call = m.group(0)
    assert "timedelta" in call or "+ timedelta" in SCRIPT, (
        f"lease claimed with an instantaneous expiry: {call}"
    )
    assert "from datetime import" in SCRIPT and "timedelta" in SCRIPT.split("from datetime import", 1)[1][:60], (
        "timedelta is not even imported"
    )


def test_approved_autofill_requires_an_explicit_url_acknowledgment():
    assert "--approved-by" in SCRIPT
    # some gate must exist: an allowlist, a per-run confirm flag, or a refusal when the profile is real
    assert any(
        token in SCRIPT
        for token in ("allowlist", "allow_url", "--i-am-applying", "i_am_applying",
                      "--confirm-apply", "acknowledge", "APPROVED_APPLY_URLS")
    ), "no guard: a --approved-by run will autofill real PII into an arbitrary live form"


def test_blocked_bundle_records_the_real_hard_stop_reason():
    """83978b8: blocked-bundle blocking_reasons is derived from capture + failed-action reasons,
    so a LEASE_LOST run is no longer reported with an empty blocking_reasons list."""
    seg = SCRIPT.split("def _write_blocked_bundle", 1)[1]
    assert 'action.get("reason")' in seg and "blocking_reasons" in seg
    # P3 (not blocking): post_fill_hard_stop is still hardcoded True even for a LEASE_LOST.


def test_p2_dead_code_write_blocked_bundle_is_now_reachable():
    """931d78d: `transcript is None` no longer raises SystemExit before _write_blocked_bundle."""
    head = SCRIPT.split("_write_blocked_bundle(", 1)[0]
    assert 'raise SystemExit("live page did not produce a transcript")' not in head
