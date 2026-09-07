import subprocess
import sys


def test_check_profile_accepts_explicitly_completed_profile(tmp_path):
    # The tracked config/candidate_profile.yaml is intentionally an all-TODO template (real PII lives
    # only in the gitignored .local.yaml), so this test points --check-profile at a complete fixture.
    profile = tmp_path / "complete.yaml"
    profile.write_text(
        "meta:\n  candidate_id: internal-test\n  schema_version: 2\n"
        "facts:\n"
        "  - {fact_id: name.full, type: identity, value: Test User, required: true}\n"
        "  - {fact_id: edu.primary.school, type: education, value: Test University, required: true}\n"
        "  - {fact_id: edu.primary.degree, type: education, value: B.S. Testing, required: true}\n"
        "  - {fact_id: edu.primary.grad_date, type: education, value: May 2027, required: true}\n"
        "  - {fact_id: auth.status, type: legal, value: authorized, required: true, literal_only: true}\n"
        "  - {fact_id: auth.needs_future_sponsorship, type: legal, value: true, required: true, literal_only: true}\n"
        "application_answers: {}\n"
    )
    result = subprocess.run(
        [sys.executable, "apply company.py", "--check-profile", "--candidate-profile", str(profile)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "Candidate profile completeness: OK"


def test_check_profile_rejects_the_todo_template():
    result = subprocess.run(
        [sys.executable, "apply company.py", "--check-profile",
         "--candidate-profile", "config/candidate_profile.yaml"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "HUMAN_REQUIRED" in result.stdout


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
