from pathlib import Path

from app.resumes.pdf_qa import run_pdf_qa


def test_compressed_real_resume_is_not_rejected_for_binary_question_bytes():
    pdf = Path("/Users/andrewweng/Downloads/Andrew Resume .pdf")
    if not pdf.exists():
        return
    result = run_pdf_qa(pdf.read_bytes())
    assert "UNSUPPORTED_TEXT_REPLACEMENT" not in result.failures
