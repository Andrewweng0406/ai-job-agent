from __future__ import annotations


LINES_PER_PAGE = 52


def render_simple_pdf(lines: list[str]) -> bytes:
    """Render a tiny selectable-text PDF using built-in primitives only."""
    pages = _paginate(lines)
    page_count = len(pages)
    font_obj_id = 3 + page_count * 2
    page_obj_ids = [3 + index * 2 for index in range(page_count)]
    content_obj_ids = [4 + index * 2 for index in range(page_count)]
    kids = " ".join(f"{obj_id} 0 R" for obj_id in page_obj_ids)

    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii")]
    for page_obj_id, content_obj_id in zip(page_obj_ids, content_obj_ids):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> /Contents {content_obj_id} 0 R >>"
            ).encode("ascii")
        )
        stream = _page_stream(pages[(page_obj_id - 3) // 2])
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _escape_pdf_text(value: str) -> str:
    safe = _pdf_safe_text(value)
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 10 Tf", "50 760 Td", "14 TL"]
    for line in lines:
        content_lines.append(f"({_escape_pdf_text(line)}) Tj")
        content_lines.append("T*")
    content_lines.append("ET")
    return "\n".join(content_lines).encode("latin-1", errors="strict")


def _paginate(lines: list[str]) -> list[list[str]]:
    if not lines:
        return [[""]]
    return [lines[index : index + LINES_PER_PAGE] for index in range(0, len(lines), LINES_PER_PAGE)]


def _pdf_safe_text(value: str) -> str:
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "*",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\xa0": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value.encode("latin-1", errors="replace").decode("latin-1")
