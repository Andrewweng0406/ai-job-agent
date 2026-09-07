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
        self._legend_text: list[str] | None = None
        self._current_legend: str | None = None

    def handle_starttag(self, tag: str, attrs_raw: list[tuple[str, str | None]]) -> None:
        attrs = {key.lower(): value or "" for key, value in attrs_raw}
        if tag == "label":
            self._label_for = attrs.get("for")
            self._label_text = []
        elif tag in {"input", "select", "textarea"}:
            element = _Element(tag, attrs)
            if self._current_legend:
                element.attrs["data-group-label"] = self._current_legend
            preceding = _clean_text(self._last_text[-1]) if self._last_text else ""
            if preceding:
                element.text = preceding
            self.controls.append(element)
            if tag in {"select", "textarea"}:
                self._control_stack.append(element)
        elif tag == "option":
            self._option_text = []
        elif tag == "legend":
            self._legend_text = []

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
        elif tag == "legend":
            self._current_legend = _clean_text(" ".join(self._legend_text or [])) or self._current_legend
            self._legend_text = None

    def handle_data(self, data: str) -> None:
        text = _clean_text(data)
        if not text:
            return
        self._last_text.append(text)
        if self._label_for is not None:
            self._label_text.append(text)
        if self._option_text is not None:
            self._option_text.append(text)
        if self._legend_text is not None:
            self._legend_text.append(text)
        if self._control_stack and self._control_stack[-1].tag == "textarea":
            self._control_stack[-1].text += f" {text}"


class HtmlFormFieldExtractor:
    def extract(self, html: str, ats_type: str = "generic") -> list[RawFormField]:
        parser = _FormHtmlParser()
        parser.feed(html)
        fields: list[RawFormField] = []
        radio_groups: dict[str, list[_Element]] = {}
        for index, control in enumerate(parser.controls):
            input_type = control.attrs.get("type", "text").lower()
            if input_type in {"hidden", "submit", "button", "reset"}:
                continue
            if input_type == "radio" and control.attrs.get("name"):
                radio_groups.setdefault(control.attrs["name"], []).append(control)
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
        for index, (name, controls) in enumerate(radio_groups.items()):
            options = [_label_for(control, parser.labels) or control.attrs.get("value", "") for control in controls]
            options = [_clean_text(option) for option in options if _clean_text(option)]
            label = _radio_group_label(name, controls, options)
            fields.append(
                RawFormField(
                    label=label,
                    kind=InputKind.SELECT,
                    selector=f"name={name}",
                    required=any(_is_required(control, label) for control in controls),
                    options=options,
                )
            )
        return fields


def _label_for(control: _Element, labels: dict[str, str]) -> str:
    control_id = control.attrs.get("id")
    if control_id and labels.get(control_id):
        return labels[control_id]
    for key in ("aria-label", "placeholder"):
        if control.attrs.get(key):
            return _clean_text(control.attrs[key])
    if control.text:
        return _clean_text(control.text)
    if control.attrs.get("name"):
        return _clean_text(control.attrs["name"])
    return ""


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


def _radio_group_label(name: str, controls: list[_Element], options: list[str]) -> str:
    for control in controls:
        if control.attrs.get("data-group-label"):
            return _clean_text(control.attrs["data-group-label"])
    for control in controls:
        text = control.text
        for option in options:
            text = re.sub(rf"\b{re.escape(option)}\b", " ", text, flags=re.I)
        text = _clean_text(text)
        if text:
            return text
    return _clean_text(name)


def _clean_text(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())
