from app.resumes.profile import CandidateProfile


def test_todo_candidate_id_gets_stable_internal_namespace(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("meta:\n  candidate_id: TODO\nfacts: []\n")
    first = CandidateProfile.from_yaml(path)
    second = CandidateProfile.from_yaml(path)
    assert first.candidate_id == second.candidate_id
    assert first.candidate_id.startswith("internal-")
    assert "TODO" not in first.candidate_id
