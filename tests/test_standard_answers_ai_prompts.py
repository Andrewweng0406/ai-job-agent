import pytest

from app.applications.standard_answers import is_experience_question


@pytest.mark.parametrize("label", [
    "What AI tools are you currently using today and how are you using them?",
    "What are some AI specific technologies you are comfortable with?",
])
def test_ai_tool_experience_prompts_use_verified_fact_drafting(label):
    assert is_experience_question(label)
