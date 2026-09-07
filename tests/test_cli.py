import subprocess
import sys


def test_check_profile_accepts_explicitly_completed_profile():
    result = subprocess.run(
        [sys.executable, "apply company.py", "--check-profile"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "Candidate profile completeness: OK"


def test_autofill_preview_cli_fails_closed_for_unknown_transcript():
    result = subprocess.run(
        [
            sys.executable,
            "apply company.py",
            "--settings",
            "config/settings.yaml",
            "--autofill-preview",
            "dry_missing",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Autofill preview unavailable" in result.stdout
