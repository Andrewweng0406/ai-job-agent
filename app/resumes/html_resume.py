"""Render the candidate's résumé as styled HTML matching their supplied template.

Content comes verbatim from the profile YAML (facts + the structured
projects/experience lists the candidate provided). Nothing is generated or
rephrased here — this is a layout layer. Per-role tailoring is limited to the
objective line and, optionally, selecting/ordering existing bullets.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from app.utils.config import load_yaml

_TEAL = "#1f7a5a"

_DEFAULT_OBJECTIVE = ("Seeking Full-Time New Grad Roles", "Data Science, AI & Analytics")


@dataclass(frozen=True, slots=True)
class ResumeData:
    name: str
    location: str
    email: str
    phone: str
    github: str
    linkedin: str
    objective: tuple[str, str]
    school: str
    degree: str
    grad_date: str
    coursework: str
    skills: list[tuple[str, str]]      # (label, value)
    projects: list[dict]               # {name, technologies, bullets[]}
    experience: list[dict]             # {employer, title, location, dates, bullets[]}


def load_resume_data(profile_path: str | Path, *, objective: tuple[str, str] | None = None) -> ResumeData:
    raw = load_yaml(str(profile_path)) or {}
    facts = {f["fact_id"]: str(f["value"]) for f in raw.get("facts", []) if "fact_id" in f}

    def fact(fid: str, default: str = "") -> str:
        v = facts.get(fid, default)
        return "" if v in ("", "TODO", "None") else v

    skills = [
        ("Programming & Data", fact("skills.programming_data")),
        ("AI & Machine Learning", fact("skills.ai_ml")),
        ("Visualization & Tools", fact("skills.visualization_tools")),
    ]
    legacy_loc = ((raw.get("personal_information") or {}).get("location") or "").strip()
    return ResumeData(
        name=fact("name.full"),
        location=legacy_loc,
        email=fact("contact.email"),
        phone=fact("contact.phone"),
        github=fact("links.github"),
        linkedin=fact("links.linkedin"),
        objective=objective or _DEFAULT_OBJECTIVE,
        school=fact("edu.primary.school"),
        degree=fact("edu.primary.degree"),
        grad_date=fact("edu.primary.grad_date"),
        coursework=fact("edu.primary.coursework"),
        skills=[(lbl, val) for lbl, val in skills if val],
        projects=[dict(p) for p in raw.get("projects", [])],
        experience=[dict(e) for e in raw.get("experience", [])],
    )


def objective_for_job(job_title: str | None) -> tuple[str, str]:
    """A full-time new-grad objective; second line nods to the role area when clear."""
    if not job_title:
        return _DEFAULT_OBJECTIVE
    t = job_title.lower()
    if any(k in t for k in ("data scien", "machine learning", "ml ", "ai ")):
        area = "Data Science, Machine Learning & AI"
    elif any(k in t for k in ("analyst", "analytics", "business intelligence", "bi ")):
        area = "Data & Business Analytics"
    elif any(k in t for k in ("product", "operations", "strategy")):
        area = "Analytics, Strategy & Operations"
    else:
        area = "Data Science, AI & Analytics"
    return ("Seeking Full-Time New Grad Roles", area)


def render_resume_html(data: ResumeData) -> str:
    e = html.escape

    def bullets(items: list[str]) -> str:
        return "".join(f"<li>{e(b)}</li>" for b in items if b)

    proj_html = ""
    for p in data.projects:
        tech = f' <span class="tech">| {e(str(p.get("technologies", "")))}</span>' if p.get("technologies") else ""
        proj_html += (
            f'<div class="entry"><div class="entry-head">{e(str(p.get("name", "")))}{tech}</div>'
            f'<ul>{bullets([str(b) for b in p.get("bullets", [])])}</ul></div>'
        )

    exp_html = ""
    for x in data.experience:
        meta = " | ".join(str(x[k]) for k in ("location", "dates") if x.get(k))
        exp_html += (
            f'<div class="entry"><div class="entry-head">{e(str(x.get("employer", "")))}'
            f' &mdash; <em>{e(str(x.get("title", "")))}</em>'
            f'{f" | {e(meta)}" if meta else ""}</div>'
            f'<ul>{bullets([str(b) for b in x.get("bullets", [])])}</ul></div>'
        )

    skills_html = "".join(
        f"<li><strong>{e(lbl)}:</strong> {e(val)}</li>" for lbl, val in data.skills
    )
    edu_line = f"{e(data.school)} &mdash; {e(data.degree)}"
    if data.grad_date:
        edu_line += f' <span class="tech">| Expected Graduation: {e(data.grad_date)}</span>'

    contact_bits: list[str] = []
    if data.location:
        contact_bits.append(e(data.location))
    if data.email:
        contact_bits.append(f'<a href="mailto:{e(data.email)}">{e(data.email)}</a>')
    if data.phone:
        contact_bits.append(e(data.phone))
    if data.github:
        contact_bits.append(f'<a href="{e(data.github)}">GitHub</a>')
    if data.linkedin:
        contact_bits.append(f'<a href="{e(data.linkedin)}">LinkedIn</a>')
    contact_line = " &nbsp;|&nbsp; ".join(contact_bits)

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: Letter; margin: 0.5in 0.55in; }}
* {{ box-sizing: border-box; }}
body {{ font: 10.5pt/1.35 "Georgia","Times New Roman",serif; color:#1a1a1a; margin:0; }}
h1 {{ text-align:center; font-size:19pt; margin:0 0 2pt; letter-spacing:.3px; }}
.contact {{ text-align:center; font-size:9pt; color:#333; margin-bottom:2pt; }}
.contact a {{ color:#333; text-decoration:none; }}
.objective {{ text-align:center; color:{_TEAL}; font-weight:bold; font-size:10pt; line-height:1.25; margin-bottom:8pt; }}
h2 {{ color:{_TEAL}; font-size:11.5pt; margin:11pt 0 2pt; border-bottom:1.2pt solid #c9c9c9; padding-bottom:1pt; }}
.entry {{ margin:4pt 0 6pt; }}
.entry-head {{ font-weight:bold; font-size:10pt; }}
.entry-head em {{ font-weight:bold; font-style:italic; }}
.tech {{ font-weight:normal; font-style:italic; color:#444; }}
ul {{ margin:2pt 0 0; padding-left:16pt; }}
li {{ margin:1.5pt 0; }}
.edu {{ font-weight:bold; }}
.coursework {{ margin-top:2pt; }}
</style></head><body>
<h1>{e(data.name)}</h1>
<div class="contact">{contact_line}</div>
<div class="objective">{e(data.objective[0])}<br>{e(data.objective[1])}</div>

<h2>Education</h2>
<div class="edu">{edu_line}</div>
{f'<div class="coursework"><strong>Relevant Coursework:</strong> {e(data.coursework)}</div>' if data.coursework else ''}

<h2>Skills &amp; Technical Proficiencies</h2>
<ul>{skills_html}</ul>

<h2>Technical Projects</h2>
{proj_html}

<h2>Professional Experience</h2>
{exp_html}
</body></html>"""
