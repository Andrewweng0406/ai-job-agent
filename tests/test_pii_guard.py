"""Guard: real candidate PII must never enter a git-tracked file.

Real values live only in `config/candidate_profile.local.yaml` (gitignored). The tracked
`config/candidate_profile.yaml` must stay a TODO-only template.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKED_PROFILE = ROOT / "config" / "candidate_profile.yaml"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d{0,3}[ .(-]?\d{3}[ ).-]?\d{3}[ .-]?\d{4}")


def _git_tracked(rel: str) -> bool:
    r = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True)
    return r.returncode == 0


def test_local_profile_override_is_gitignored():
    r = subprocess.run(["git", "check-ignore", "config/candidate_profile.local.yaml"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "candidate_profile.local.yaml" in r.stdout


def test_local_profile_is_not_tracked():
    assert not _git_tracked("config/candidate_profile.local.yaml")
    for p in subprocess.run(["git", "ls-files", "config/"], cwd=ROOT, capture_output=True, text=True).stdout.split():
        assert not p.endswith(".local.yaml"), f"a *.local.yaml file is tracked: {p}"


def test_tracked_candidate_profile_has_no_real_pii():
    text = TRACKED_PROFILE.read_text()
    # every `required: true` fact in the tracked template must still be TODO
    for m in re.finditer(r"value:\s*(.+)\n\s*required:\s*true", text):
        assert m.group(1).strip() in {"TODO", "[]", "''", '""'}, f"tracked profile has a real required value: {m.group(1)!r}"
    # no email / phone shaped strings anywhere in the tracked file
    assert not _EMAIL.search(text), f"tracked profile contains an email: {_EMAIL.search(text).group(0)}"
    assert not _PHONE.search(text.replace("2027", "").replace("2026", "")), "tracked profile contains a phone-shaped string"
    # legacy block also all-TODO
    for key in ("full_name", "email", "phone", "location"):
        assert re.search(rf"{key}:\s*TODO", text), f"{key} is not TODO in the tracked template"


def test_no_tracked_file_contains_the_candidate_name_or_contact():
    """Cheap belt-and-braces: scan the whole tracked tree for the known real identifiers."""
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    needles = ("andrewweng.weng@sjsu.edu", "sheng-po-weng-029190352")
    hits = []
    for rel in tracked:
        if rel.startswith((".git/",)) or rel.endswith((".png", ".pdf", ".sqlite3")):
            continue
        try:
            body = (ROOT / rel).read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for n in needles:
            if n in body:
                hits.append((rel, n))
    assert not hits, f"real candidate contact info found in tracked files: {hits}"
