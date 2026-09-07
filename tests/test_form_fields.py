from app.applications.form_fields import classify_label, resolve_value
from app.models.enums import QuestionAnswerState
from app.resumes.profile import CandidateProfile


def test_unknown_legal_field_routes_to_human():
    spec = classify_label("Describe your immigration status and work restrictions")
    result = resolve_value(spec, _profile({}))
    assert result.state == QuestionAnswerState.HUMAN_REQUIRED


def test_authorization_field_requires_canonical_answer():
    spec = classify_label("Are you authorized to work in the United States?")
    result = resolve_value(spec, _profile({}))
    assert result.state == QuestionAnswerState.HUMAN_REQUIRED
    assert result.reason == "MISSING_CANONICAL_ANSWER:work_authorized_us"


def test_demographic_field_defaults_to_decline():
    spec = classify_label("Gender")
    result = resolve_value(spec, _profile({}))
    assert result.state == QuestionAnswerState.AUTO_SAFE
    assert result.value == "Decline to self-identify"


def _profile(answers):
    return CandidateProfile(candidate_id="cand", schema_version=2, facts={}, application_answers=answers)

