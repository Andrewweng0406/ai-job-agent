from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.applications.form_engine import FormFieldResolution, FormFieldStatus, InputKind


@dataclass(frozen=True, slots=True)
class BrowserAutofillResult:
    filled_selectors: list[str]
    upload_call_count: int
    final_submit_call_count: int = 0


class DryRunBrowserAutofill:
    """Applies only resolved transcript values and exposes no submit operation."""

    def apply(
        self,
        page,
        resolutions: list[FormFieldResolution],
        *,
        expected_resume_hash: str,
    ) -> BrowserAutofillResult:
        filled: list[str] = []
        uploads = 0
        for resolution in resolutions:
            if resolution.status != FormFieldStatus.FILLED or resolution.value is None:
                continue
            locator = page.locator(_playwright_selector(resolution.selector))
            value = resolution.value
            if resolution.kind == InputKind.FILE:
                _assert_artifact_hash(value, expected_resume_hash)
                locator.set_input_files(value)
                uploads += 1
                observed = Path(value).name
                actual = Path(locator.input_value()).name
            elif resolution.kind == InputKind.SELECT:
                if locator.get_attribute("role") in {"combobox", "listbox"}:
                    locator.fill(value)
                else:
                    locator.select_option(label=value)
                observed = value
                actual = locator.input_value()
            elif resolution.kind == InputKind.BOOL:
                locator.set_checked(value.strip().lower() in {"true", "yes", "1"})
                observed = value.strip().lower() in {"true", "yes", "1"}
                actual = locator.is_checked()
            else:
                locator.fill(value)
                observed = value
                actual = locator.input_value()
            if actual != observed:
                raise RuntimeError(f"BROWSER_TRANSCRIPT_MISMATCH:{resolution.selector}")
            filled.append(resolution.selector)
        return BrowserAutofillResult(filled, uploads)


def _playwright_selector(selector: str) -> str:
    key, separator, value = selector.partition("=")
    if separator and key in {"id", "name", "data-testid", "aria-label"}:
        escaped = value.replace('"', '\\"')
        return f'[{key}="{escaped}"]'
    return selector


def _assert_artifact_hash(path: str, expected_hash: str) -> None:
    artifact = Path(path)
    if not artifact.is_file():
        raise RuntimeError("RESUME_ARTIFACT_MISSING")
    actual = sha256(artifact.read_bytes()).hexdigest()
    normalized = expected_hash.removeprefix("sha256:")
    if actual != normalized:
        raise RuntimeError("RESUME_ARTIFACT_HASH_MISMATCH")
