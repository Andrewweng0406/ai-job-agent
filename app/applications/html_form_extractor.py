from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import re

from app.applications.form_engine import InputKind, RawFormField


@dataclass(slots=True)
class _Element:
    tag: str
    attrs: dict[str, str]
    text: str = ""
    options: list[str] = field(default_factory=list)


class _FormHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.labels: dict[str, str] = {}
        self.controls: list[_Element] = []
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self._control_stack: list[_Element] = []
        self._option_text: list[str] | None = None
        self._last_text: list[str] = []

    def handle_starttag(self, tag: str, attrs_raw: list[tuple[str, str | None]]) -> None:
        attrs = {key.lower(): value or "" for key, value in attrs_raw}
        if tag == "label":
            self._label_for = attrs.get("for")
            self._label_text = []
        elif tag in {"input", "select", "textarea"}:
            element = _Element(tag, attrs)
            preceding = _clean_text(" ".join(self._last_text[-3:]))
            if preceding:
                element.text = preceding
            self.controls.append(element)
            if tag in {"select", "textarea"}:
                self._control_stack.append(element)
        elif tag == "option":
            self._option_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            if self._label_for:
                self.labels[self._label_for] = _clean_text(" ".join(self._label_text))
            self._label_for = None
            self._label_text = []
        elif tag in {"select", "textarea"} and self._control_stack:
            self._control_stack.pop()
        elif tag == "option":
            option = _clean_text(" ".join(self._option_text or []))
            if option and self._control_stack:
                self._control_stack[-1].options.append(option)
            self._option_text = None

    def handle_data(self, data: str) -> None:
        text = _clean_text(data)
        if not text:
            return
        self._last_text.append(text)
        if self._label_for is not None:
            self._label_text.append(text)
        if self._option_text is not None:
            self._option_text.append(text)
        if self._control_stack and self._control_stack[-1].tag == "textarea":
            self._control_stack[-1].text += f" {text}"


class HtmlFormFieldExtractor:
    def extract(self, html: str, ats_type: str = "generic") -> list[RawFormField]:
        parser = _FormHtmlParser()
        parser.feed(html)
        fields: list[RawFormField] = []
        for index, control in enumerate(parser.controls):
            input_type = control.attrs.get("type", "text").lower()
            if input_type in {"hidden", "submit", "button", "reset"}:
                continue
            label = _label_for(control, parser.labels)
            if not label:
                continue
            fields.append(
                RawFormField(
                    label=label,
                    kind=_kind_for(control.tag, input_type, control.attrs, control.options),
                    selector=_selector_for(control, index, ats_type),
                    required=_is_required(control, label),
                    options=control.options,
                )
            )
        return fields


def _label_for(control: _Element, labels: dict[str, str]) -> str:
    control_id = control.attrs.get("id")
    if control_id and labels.get(control_id):
        return labels[control_id]
    for key in ("aria-label", "placeholder", "name"):
        if control.attrs.get(key):
            return _clean_text(control.attrs[key])
    return _clean_text(control.text)


def _kind_for(tag: str, input_type: str, attrs: dict[str, str], options: list[str]) -> InputKind:
    if tag == "textarea":
        return InputKind.LONG_TEXT
    if tag == "select":
        return InputKind.SELECT
    if input_type == "file":
        return InputKind.FILE
    if input_type in {"checkbox", "radio"}:
        return InputKind.BOOL
    if input_type in {"number", "range"}:
        return InputKind.NUMERIC
    if input_type in {"date", "month"}:
        return InputKind.DATE
    if options:
        return InputKind.SELECT
    return InputKind.TEXT


def _selector_for(control: _Element, index: int, ats_type: str) -> str:
    for key in ("id", "name", "data-testid", "aria-label"):
        value = control.attrs.get(key)
        if value:
            return f"{key}={value}"
    return f"{ats_type}:field:{index}"


def _is_required(control: _Element, label: str) -> bool:
    attrs = control.attrs
    class_text = attrs.get("class", "")
    return (
        "required" in attrs
        or attrs.get("aria-required", "").lower() == "true"
        or "required" in class_text.lower()
        or label.rstrip().endswith("*")
    )


def _clean_text(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())
