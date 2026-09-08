"""The HTML résumé renderer is a layout layer: verbatim profile content, corrected
objective line, no TODO/placeholder leakage, deterministic output."""
from __future__ import annotations

import pytest

from app.resumes.html_resume import (
    load_resume_data, objective_for_job, render_resume_html,
)

PROFILE = """
meta: {candidate_id: internal-test, schema_version: 2}
facts:
  - {fact_id: name.full, type: identity, value: Test Candidate}
  - {fact_id: contact.email, type: contact, value: a@sjsu.edu}
  - {fact_id: contact.phone, type: contact, value: "(415) 555-0000"}
  - {fact_id: links.github, type: link, value: https://github.com/testcand}
  - {fact_id: links.linkedin, type: link, value: https://linkedin.com/in/x}
  - {fact_id: edu.primary.school, type: education, value: San Jose State University}
  - {fact_id: edu.primary.degree, type: education, value: B.S. in Data Science}
  - {fact_id: edu.primary.grad_date, type: education, value: May 2027}
  - {fact_id: edu.primary.coursework, type: education, value: "Data Analytics, Operations Research"}
  - {fact_id: skills.programming_data, type: skill, value: "Python, SQL"}
  - {fact_id: skills.ai_ml, type: skill, value: "NLP, ARIMA"}
  - {fact_id: skills.visualization_tools, type: skill, value: "Tableau, Power BI"}
  - {fact_id: salary.floor, type: other, value: TODO}
personal_information: {location: "San Jose, CA, USA"}
projects:
  - name: Earnings Radar
    technologies: Python, NLP
    bullets: ["Parsed transcripts across 50+ stocks.", "Built dashboards at 85% accuracy."]
experience:
  - employer: Alpha Stock
    title: President
    location: Berkeley, CA
    dates: March 2024 - May 2025
    bullets: ["Led 15+ analysts."]
"""


@pytest.fixture
def data(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(PROFILE)
    return load_resume_data(p, objective=objective_for_job("Business Analyst (New Grad)"))


def test_all_profile_content_is_present(data):
    html = render_resume_html(data)
    for needle in ("Test Candidate", "a@sjsu.edu", "(415) 555-0000",
                   "San Jose State University", "B.S. in Data Science", "May 2027",
                   "Data Analytics, Operations Research", "Python, SQL", "NLP, ARIMA",
                   "Earnings Radar", "Parsed transcripts across 50+ stocks.",
                   "Alpha Stock", "President", "Led 15+ analysts."):
        assert needle in html, needle


def test_links_render_as_short_labels_not_raw_urls(data):
    html = render_resume_html(data)
    assert ">GitHub<" in html and ">LinkedIn<" in html
    assert 'href="https://github.com/testcand"' in html


def test_objective_is_full_time_new_grad_not_internship(data):
    html = render_resume_html(data)
    assert "Seeking Full-Time New Grad Roles" in html
    assert "Internship" not in html
    assert "2026" not in html


def test_no_placeholder_values_leak(data):
    html = render_resume_html(data)
    assert "TODO" not in html
    assert "None" not in html.replace("None-", "")  # guard, no stray python None


def test_render_is_deterministic(data):
    assert render_resume_html(data) == render_resume_html(data)


@pytest.mark.parametrize("title,expected2", [
    ("Data Scientist, New Grad", "Data Science, Machine Learning & AI"),
    ("Business Analyst", "Data & Business Analytics"),
    ("Product Operations Associate", "Analytics, Strategy & Operations"),
    ("Software Engineer", "Data Science, AI & Analytics"),
    (None, "Data Science, AI & Analytics"),
])
def test_objective_area_tracks_role(title, expected2):
    line1, line2 = objective_for_job(title)
    assert line1 == "Seeking Full-Time New Grad Roles"
    assert line2 == expected2
