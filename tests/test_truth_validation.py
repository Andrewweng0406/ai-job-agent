from app.resumes.truth_validation import validate_claims_against_profile


def test_truth_validation_rejects_unsupported_claims():
    result = validate_claims_against_profile(
        claims=["Python", "AWS Certified"],
        supported_facts=["Python", "SQL"],
    )
    assert not result.valid
    assert result.unsupported_claims == ["AWS Certified"]

