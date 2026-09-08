#!/usr/bin/env python3
"""Build the candidate's résumé PDF from their profile YAML, in their template style.

  build_resume.py --out data/resumes/andrew_weng_master.pdf
  build_resume.py --job-title "Business Analyst (New Grad)" --out data/resumes/robinhood.pdf

Content is verbatim from the profile (facts + supplied projects/experience). The only
per-role change is the objective line.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.resumes.html_resume import load_resume_data, objective_for_job, render_resume_html
from app.resumes.pdf_render import html_to_pdf_bytes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="config/candidate_profile.local.yaml")
    ap.add_argument("--job-title", default=None, help="tailor the objective line to this role")
    ap.add_argument("--out", default="data/resumes/andrew_weng_master.pdf")
    ap.add_argument("--html-out", default=None, help="also write the intermediate HTML")
    args = ap.parse_args()

    objective = objective_for_job(args.job_title)
    data = load_resume_data(args.profile, objective=objective)
    if not data.name or not data.school:
        print("profile is missing name/school — fill config/candidate_profile.local.yaml")
        return 1

    doc = render_resume_html(data)
    if args.html_out:
        Path(args.html_out).write_text(doc, encoding="utf-8")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(html_to_pdf_bytes(doc))
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
    print(f"objective: {objective[0]} — {objective[1]}")
    print(f"projects: {len(data.projects)} | experience: {len(data.experience)} | skill groups: {len(data.skills)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
