"""PDF résumé QA red team (Round 3 WS3).

The current renderer `app/resumes/pdf.render_simple_pdf` is a placeholder. These tests pin the
properties a résumé PDF must have before it can enter a browser upload path (PDF_RESUME_QA.md), and
document where the placeholder silently corrupts content (CLAUDE_REVIEW P2-11).
"""
from __future__ import annotations

import re
import subprocess

import pytest

from app.resumes.pdf import render_simple_pdf


def _pdftotext(pdf: bytes) -> str | None:
    try:
        out = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


def test_pdf_has_header_and_is_syntactically_bounded():
    pdf = render_simple_pdf(["Jane Q Student", "Education", "San Jose State University"])
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in pdf


def test_pdf_is_deterministic():
    lines = ["Jane Q Student", "Experience", "Built dashboards"]
    assert render_simple_pdf(lines) == render_simple_pdf(lines)


def test_text_is_selectable_and_contains_the_name():
    pdf = render_simple_pdf(["Jane Q Student", "B.S. Business Analytics", "Skills: SQL, Python"])
    text = _pdftotext(pdf)
    if text is None:
        pytest.skip("pdftotext not available")
    assert "Jane Q Student" in text


# --- CLAUDE_REVIEW P2-11: silent corruption regression guards ---
def test_long_bullet_is_not_silently_truncated():
    bullet = "Led cross-functional analytics initiatives across finance, product and operations teams over two semesters"  # 104
    bullet = bullet + " and documented the results"  # push past 110
    pdf = render_simple_pdf([bullet])
    text = _pdftotext(pdf) or pdf.decode("latin-1", "replace")
    assert bullet in text, "the full bullet text must be present; the renderer truncated it"


def test_unicode_punctuation_survives():
    pdf = render_simple_pdf(["Impact — improved reporting • saved time"])
    text = _pdftotext(pdf) or pdf.decode("latin-1", "replace")
    assert "?" not in text.split("Impact")[-1][:40], "em dash / bullet were replaced with '?'"


def test_many_lines_do_not_overflow_the_page():
    lines = [f"Line {i}: a resume bullet describing measurable, fact-backed work" for i in range(70)]
    pdf = render_simple_pdf(lines)
    # a 792pt page at 14pt leading starting near y=760 fits ~54 lines; 70 must paginate or be rejected
    assert pdf.count(b"/Type /Page ") >= 2 or b"OVERFLOW" in pdf


# --- the gate that must exist regardless of the renderer ---
def test_pdf_qa_module_exists_for_upload_gate():
    """A PDF that fails QA must never enter browser upload (PDF_RESUME_QA.md sec.3)."""
    from app.resumes import pdf_qa

    assert hasattr(pdf_qa, "run_pdf_qa") or hasattr(pdf_qa, "PdfQaResult")


def test_pdf_qa_accepts_parentheses_escaped_by_pdf_renderer():
    from app.resumes.pdf import render_simple_pdf
    from app.resumes.pdf_qa import run_pdf_qa

    line = "Phone: (415) 555-0100"
    assert run_pdf_qa(render_simple_pdf([line]), [line]).passed
