from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PdfQaResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def run_pdf_qa(pdf: bytes, expected_text: list[str] | None = None) -> PdfQaResult:
    failures: list[str] = []
    if not pdf.startswith(b"%PDF-"):
        failures.append("PDF_HEADER_MISSING")
    if not pdf.rstrip().endswith(b"%%EOF"):
        failures.append("PDF_EOF_MISSING")
    if b"/Type /Catalog" not in pdf:
        failures.append("PDF_CATALOG_MISSING")
    if b"?" in _content_stream_bytes(pdf):
        failures.append("UNSUPPORTED_TEXT_REPLACEMENT")
    if expected_text:
        decoded = pdf.decode("latin-1", "replace")
        for line in expected_text:
            safe_line = _safe_text(line)
            if safe_line and safe_line not in decoded:
                failures.append(f"TEXT_MISSING:{safe_line[:40]}")
    return PdfQaResult(passed=not failures, failures=failures)


def _content_stream_bytes(pdf: bytes) -> bytes:
    chunks: list[bytes] = []
    marker = b"stream\n"
    end = b"\nendstream"
    start = 0
    while True:
        stream_start = pdf.find(marker, start)
        if stream_start < 0:
            break
        content_start = stream_start + len(marker)
        stream_end = pdf.find(end, content_start)
        if stream_end < 0:
            break
        chunks.append(pdf[content_start:stream_end])
        start = stream_end + len(end)
    return b"\n".join(chunks)


def _safe_text(value: str) -> str:
    return (
        value.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2022", "*")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\xa0", " ")
        .encode("latin-1", errors="replace")
        .decode("latin-1")
    )
