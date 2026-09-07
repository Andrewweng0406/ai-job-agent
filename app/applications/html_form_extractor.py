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
            if self._label_for is None:
                self._label_for = "__implicit__"
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
                label = _clean_label(" ".join(self._label_text)) if self._label_for == "__implicit__" else _clean_text(" ".join(self._label_text))
                if self._label_for == "__implicit__" and self.controls:
                    self.controls[-1].text = label
                else:
                    self.labels[self._label_for] = label
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
        labelled_text = _element_text_by_id(html)
        fields: list[RawFormField] = []
        radio_groups: dict[str, list[_Element]] = {}
        for index, control in enumerate(parser.controls):
            input_type = control.attrs.get("type", "text").lower()
            if input_type in {"hidden", "submit", "button", "reset"}:
                continue
            if _is_noninteractive(control):
                continue
            if input_type == "radio" and control.attrs.get("name"):
                radio_groups.setdefault(control.attrs["name"], []).append(control)
                continue
            label = _label_for(control, parser.labels, labelled_text)
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
            options = [_label_for(control, parser.labels, labelled_text) or control.attrs.get("value", "") for control in controls]
            options = [_clean_label(option) for option in options if _clean_label(option)]
            label = _radio_group_label(name, controls, options, html)
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


def _label_for(control: _Element, labels: dict[str, str], labelled_text: dict[str, str]) -> str:
    control_id = control.attrs.get("id")
    if control_id and labels.get(control_id):
        return labels[control_id]
    labelled_by = control.attrs.get("aria-labelledby", "").split()
    accessible_label = _clean_text(" ".join(labelled_text.get(item, "") for item in labelled_by))
    if accessible_label:
        return accessible_label
    for key in ("aria-label", "placeholder"):
        if control.attrs.get(key):
            return _clean_text(control.attrs[key])
    if control.text:
        return _clean_text(control.text)
    if control.attrs.get("name"):
        return _clean_text(control.attrs["name"])
    return ""


def _is_noninteractive(control: _Element) -> bool:
    attrs = control.attrs
    if "hidden" in attrs or "disabled" in attrs or attrs.get("aria-hidden", "").lower() == "true":
        return True
    style = attrs.get("style", "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style or "opacity:0" in style:
        return True
    if attrs.get("tabindex") == "-1" and ("hidden" in attrs.get("class", "").lower() or "offscreen" in attrs.get("class", "").lower()):
        return True
    return "position:absolute" in style and bool(re.search(r"(?:left|top):-?9\d{3,}", style))


def _kind_for(tag: str, input_type: str, attrs: dict[str, str], options: list[str]) -> InputKind:
    if tag == "textarea":
        return InputKind.LONG_TEXT
    if tag == "select" or attrs.get("role", "").lower() in {"combobox", "listbox"}:
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


def _radio_group_label(name: str, controls: list[_Element], options: list[str], html: str) -> str:
    group = re.search(r'class=["\'][^"\']*application-label[^"\']*["\'][^>]*>(.*?)</[^>]+>.*?name=["\']' + re.escape(name) + r'["\']', html, re.I | re.S)
    if group:
        return _clean_label(group.group(1))
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


def _clean_label(value: str) -> str:
    return _clean_text(re.sub(r"[\*✱]+", " ", value))


def _clean_text(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


def _element_text_by_id(html: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in re.finditer(
        r'<(?P<tag>[a-zA-Z][\w:-]*)[^>]*\bid=["\'](?P<id>[^"\']+)["\'][^>]*>(?P<body>.*?)</(?P=tag)>',
        html,
        flags=re.I | re.S,
    ):
        text = _clean_text(match.group("body"))
        if text:
            values[match.group("id")] = text
    return values
