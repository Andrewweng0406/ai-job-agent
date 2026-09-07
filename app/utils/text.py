from __future__ import annotations

from html import unescape
from html.parser import HTMLParser


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if cleaned:
            self.parts.append(cleaned)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _HtmlTextExtractor()
    parser.feed(unescape(value))
    return "\n".join(parser.parts)


def normalize_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    compact = value.replace(" ", "").replace("-", "").replace("_", "").lower()
    if compact in {"fulltime", "full"}:
        return "FULL_TIME"
    if compact in {"parttime", "part"}:
        return "PART_TIME"
    if compact in {"intern", "internship"}:
        return "INTERNSHIP"
    if compact in {"contract", "contractor"}:
        return "CONTRACT"
    return value.upper()

