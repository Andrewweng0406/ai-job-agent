# PDF_RESUME_QA.md — PDF / ATS Résumé QA Spec

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Purpose:** requirements + automated checks for the résumé PDF, so generated résumés parse cleanly in
ATS résumé parsers and remain reproducible.

---

## 1. Requirements

| # | Requirement | Why |
|---|---|---|
| R1 | **Selectable text** — no image-of-text. `pdftotext` must return the full content. | ATS parsers OCR poorly / not at all. |
| R2 | **Single-column layout.** No side-by-side columns, no text boxes. | Multi-column reflows to garbage in most parsers. |
| R3 | **Standard section headings** — `Education`, `Experience`, `Projects`, `Skills`, `Leadership`. Plain text, not stylized glyphs. | Parsers key on heading strings. |
| R4 | **No important text in headers/footers.** Page number only, if anything. | Many parsers drop header/footer regions. |
| R5 | **No complex tables.** Skills as comma/pipe lists, not grids. | Tables serialize unpredictably. |
| R6 | **Consistent date format** everywhere: `Mon YYYY` (e.g. `May 2026`), ranges `Mon YYYY – Mon YYYY` or `– Present`. | Date parsing + human trust. |
| R7 | **Consistent typography** — one body font, ≤2 sizes, ≤2 weights. Embed fonts (no substitution). | Rendering stability + parse cleanliness. |
| R8 | **One page** for a new grad (target; hard-fail at 2). | Convention; also a proxy for over-claiming. |
| R9 | **Deterministic generation** — same inputs ⇒ byte-identical PDF (fixed metadata, fixed timestamp, fixed font subset order). | Reproducibility, caching, audit. |
| R10 | **Stable content hash** — `sha256` of the PDF stored on the artifact; equals a re-render's hash. | Change detection, approval integrity. |
| R11 | **Filename sanitized** — `^[A-Za-z0-9._-]+$`, `<= 100` chars, pattern `Firstname_Lastname_Role.pdf` (role slugified). No spaces, no PII beyond name. | ATS upload + filesystem safety. |
| R12 | **Text matches the structured source** — every bullet in the JSON résumé representation appears in the PDF text and vice-versa. | The validated artifact is what gets sent. |
| R13 | **Required facts present in text** — name, school, degree, graduation month+year. | Omission check (`RESUME_TRUTH_SYSTEM.md` §4 step 6). |
| R14 | **No tracked-changes / comments / form fields / JavaScript / external links to file://**. | Cleanliness + safety. |
| R15 | **PDF/A-ish**: metadata `Title`, `Author` = candidate name; `Producer` fixed; no `CreationDate` drift. | Determinism. |
| R16 | **ASCII-safe fallback** — non-ASCII (em dash, bullet glyph) render but also survive `pdftotext` as sane characters. | Parser robustness. |

---

## 2. Automated checks (`app/resumes/pdf_qa.py` + `tests/test_pdf_resume_qa.py`)

```python
@dataclass(frozen=True)
class PdfQaResult:
    ok: bool
    failures: list[str]          # e.g. ["R2_MULTI_COLUMN", "R8_TWO_PAGES"]
    warnings: list[str]
    page_count: int
    text: str
    content_hash: str
```

| Check | Implementation (stdlib / lightweight) |
|---|---|
| R1 selectable text | extract text (pypdf / pdfminer); `len(text.split()) >= 120` and contains the candidate name |
| R2 single column | heuristic: for each page, cluster text x-positions; >1 dense cluster band with a wide gutter ⇒ fail |
| R3 headings | regex for each expected heading on its own line |
| R4 header/footer | text within top/bottom 4% of page height must be empty or `^\d+$` |
| R5 tables | no run of ≥3 lines with ≥3 aligned column x-positions |
| R6 dates | all date-like substrings match the single canonical regex; no mixed `2026`/`05/2026`/`May '26` |
| R7 fonts | `pdffonts`-style: ≤2 embedded families, all `emb=yes` |
| R8 pages | `page_count == 1` fail>1; warn if content height < 55% (too sparse) |
| R9/R10 determinism | render twice in the test; assert identical `content_hash` |
| R11 filename | regex + length |
| R12 parity | set(bullets_from_json) == set(bullet_lines_from_pdf_text) (normalized) |
| R13 omission | name, school, degree, `Mon YYYY` grad date all present |
| R14 safety | no `/AcroForm`, `/JavaScript`, `/JS`, `/RichMedia`, annotations of type Popup/Text |
| R15 metadata | Title/Author set; Producer == expected constant; no CreationDate or a fixed one |
| R16 non-ascii | `pdftotext` round-trip of `–`, `•`, `—` yields `-`/`*`/`-` or the same char, not `�` |

`ok = not failures`. Warnings don't block but surface in the daily report.

---

## 3. Integration points

- Résumé pipeline: after render, run `pdf_qa`; any `failures` ⇒ `resume_artifact.validation_status =
  PDF_QA_FAILED` ⇒ application → `HUMAN_REQUIRED` (`RESUME_UPLOAD`/`OTHER`). Never upload a failing PDF.
- Store `PdfQaResult` (minus `text`) on the artifact.
- The dry-run transcript references `resume_artifact.file_hash` = `content_hash`; the browser adapter
  asserts the uploaded file's hash equals the approved one.

---

## 4. Non-goals (for now)

- Visual design polish / ATS "score" services — out of scope.
- Multiple templates per persona — one clean template per persona is enough for v1.
- DOCX output — PDF only.
