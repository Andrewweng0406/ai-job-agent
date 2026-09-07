import subprocess
import sys


def test_check_profile_reports_missing_required_facts():
    result = subprocess.run(
        [sys.executable, "apply company.py", "--check-profile"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Candidate profile completeness: HUMAN_REQUIRED" in result.stdout
    assert "name.full" in result.stdout


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
