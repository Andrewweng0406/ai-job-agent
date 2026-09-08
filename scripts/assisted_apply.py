#!/usr/bin/env python3
"""Human-in-the-loop assisted apply. Two steps, neither of which submits:

  packet  navigate a live application form, capture it, and write a review packet
          (profile-safe pre-fill + the required questions you must answer).

  fill    after you have written answers.yaml and approved it, open the form,
          fill the safe fields + your answers, screenshot it, and STOP. You
          review the browser window and click Submit yourself.

There is no code path here that submits: no button click on a submit control, no
requestSubmit, no Enter key, no adapter with submission enabled.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.applications.browser_autofill import DryRunBrowserAutofill
from app.applications.browser_capture import BrowserFieldCapture
from app.applications.form_engine import InputKind, resolve_form_field
from app.applications.review_packet import build_review_packet
from app.applications.assisted_answers import load_answers
from app.resumes.profile import CandidateProfile
from scripts.live_dry_run import _sanitize_html, _resolve_profile_path


def _launch(playwright, headed: bool):
    return playwright.chromium.launch(headless=not headed)


def cmd_packet(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = CandidateProfile.from_yaml(_resolve_profile_path(args.profile))

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = _launch(pw, headed=False)
        page = browser.new_context().new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            title = page.title()
            page.screenshot(path=str(out / "before_fill.png"), full_page=True)
            html = page.content()
            capture = BrowserFieldCapture().capture(page, ats_type=args.ats)
            if capture.human_required:
                (out / "packet.json").write_text(json.dumps(
                    {"blocked": True, "reasons": capture.blocking_reasons, "url": args.url}, indent=2))
                (out / "dom.sanitized.html").write_text(_sanitize_html(html), encoding="utf-8")
                print(f"BLOCKED: {capture.blocking_reasons} — see {out}")
                return 2

            resolutions = [resolve_form_field(f, profile, args.resume_pdf or "",
                                              resume_validated=bool(args.resume_pdf))
                           for f in capture.fields]
            role = _role_from_title(title, args.role)
            packet = build_review_packet(
                company=args.company, role=role, apply_url=args.url, ats=args.ats,
                raw_fields=capture.fields, resolutions=resolutions,
            )
            selectors = {f"q{i}": r.selector for i, r in enumerate(resolutions)
                         if r.status.value in {"HUMAN_REQUIRED", "BLOCKED"}}
            # Harvest options for react-select widgets so the reviewer sees real choices.
            live_options = _harvest_options(page, selectors)
        finally:
            browser.close()

    (out / "dom.sanitized.html").write_text(_sanitize_html(html), encoding="utf-8")
    packet_dict = packet.to_dict()
    for q in packet_dict["needs_your_answer"]:
        if not q["options"] and q["field_id"] in live_options:
            q["options"] = live_options[q["field_id"]]
    (out / "field_selectors.json").write_text(json.dumps(selectors, indent=2, sort_keys=True))
    (out / "packet.json").write_text(json.dumps(packet_dict, indent=2, sort_keys=True))
    (out / "packet.md").write_text(packet.to_markdown(), encoding="utf-8")

    print(packet.to_markdown())
    print(f"\nWrote {out}/packet.md — fill in {out}/answers.yaml and run: "
          f"assisted_apply.py fill --packet {out}")
    return 0


def cmd_fill(args) -> int:
    packet_dir = Path(args.packet)
    packet_raw = json.loads((packet_dir / "packet.json").read_text())
    if packet_raw.get("blocked"):
        print("packet is blocked; cannot fill")
        return 2
    from app.applications.review_packet import ReviewPacket
    packet = ReviewPacket.from_dict(packet_raw)
    approved = load_answers(args.answers or (packet_dir / "answers.yaml"), packet)
    selectors = json.loads((packet_dir / "field_selectors.json").read_text())
    answer_by_selector = {selectors[fid]: val for fid, val in approved.answers.items() if fid in selectors}
    profile = CandidateProfile.from_yaml(_resolve_profile_path(args.profile))

    print(f"Approved by {approved.approved_by} at {approved.approved_at}")
    print(f"Safe pre-fill: {len(packet.safe_prefill)} fields; your answers: {len(answer_by_selector)} fields")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = _launch(pw, headed=args.headed)
        page = browser.new_context().new_page()
        try:
            page.goto(packet.apply_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
            capture = BrowserFieldCapture().capture(page, ats_type=packet.ats)
            if capture.human_required:
                print(f"BLOCKED on re-navigation: {capture.blocking_reasons}")
                return 2
            resolutions = [resolve_form_field(f, profile, args.resume_pdf or "",
                                              resume_validated=bool(args.resume_pdf))
                           for f in capture.fields]
            filled = DryRunBrowserAutofill().apply(page, resolutions, expected_resume_hash=_hash(args.resume_pdf))
            for selector, value in answer_by_selector.items():
                _fill_one(page, selector, value)
            page.screenshot(path=str(packet_dir / "after_fill.png"), full_page=True)
            print(f"\nFilled {len(filled.filled_selectors)} profile fields + {len(answer_by_selector)} of your answers.")
            print("The form has NOT been submitted. Review it and click Submit yourself.")
            if args.headed and args.keep_open_seconds > 0:
                print(f"Browser stays open for {args.keep_open_seconds}s — review and submit.")
                page.wait_for_timeout(args.keep_open_seconds * 1000)
            elif args.headed:
                input("\nPress Enter here to close the browser once you are done...")
        finally:
            browser.close()
    return 0


def _harvest_options(page, selectors: dict[str, str]) -> dict[str, list[str]]:
    """Open each native <select> / react-select and record its option labels,
    scoping to the menu THIS control owns so options don't bleed between fields."""
    found: dict[str, list[str]] = {}
    for field_id, selector in selectors.items():
        loc = page.locator(_css(selector))
        if loc.count() == 0:
            continue
        try:
            tag = (loc.evaluate("el => el.tagName") or "").lower()
            if tag == "select":
                opts = loc.evaluate("el => [...el.options].map(o => o.text.trim()).filter(Boolean)")
                if opts:
                    found[field_id] = opts[:300]
                continue
            if not loc.evaluate("el => !!el.closest('[class*=\"-control\"],[class*=\"select__\"]')"):
                continue
            _close_menus(page)
            loc.scroll_into_view_if_needed()
            loc.click()
            page.wait_for_timeout(350)
            listbox_id = loc.get_attribute("aria-controls") or loc.get_attribute("aria-owns")
            if listbox_id:
                opts = page.locator(f'#{listbox_id} [role="option"]').all_inner_texts()
            else:
                opts = page.locator('[role="listbox"]:visible [role="option"]').all_inner_texts()
            _close_menus(page)
            cleaned = [re.sub(r"\+\d+$", "", o.strip()).strip() for o in opts if o.strip()]
            if cleaned:
                found[field_id] = list(dict.fromkeys(cleaned))[:300]
        except Exception:
            _close_menus(page)
            continue
    return found


def _close_menus(page) -> None:
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    except Exception:
        pass


def _fill_one(page, selector: str, value: str) -> None:
    """fill / select / check / upload only — never a click on a submit control, never Enter.

    Handles native <select> (with fuzzy option matching), checkboxes/radios,
    react-select comboboxes, file inputs, and plain text. A choice value that does
    not resemble any offered option is skipped rather than guessed.

    A `q=<question text>` selector is a grouped control (radio / checkbox / Yes-No
    buttons) located by its question label — used by the Playwright-native scanner.
    """
    if selector.startswith("q="):
        _fill_group_by_question(page, selector[2:], value)
        return
    loc = page.locator(_css(selector)).first
    if page.locator(_css(selector)).count() == 0:
        raise RuntimeError(f"FILL_SELECTOR_NOT_FOUND:{selector}")
    try:
        loc.wait_for(state="attached", timeout=4_000)
        loc.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass
    try:
        meta = loc.evaluate(
            "el => ({tag: el.tagName, type: el.getAttribute('type')||'', role: el.getAttribute('role')||'',"
            " rs: !!el.closest('.select__control,[class*=\"-control\"],[class*=\"select__\"]')})",
            timeout=4_000,
        )
    except Exception:
        raise RuntimeError(f"FILL_ELEMENT_UNSTABLE:{selector}")
    tag = (meta["tag"] or "").lower()
    input_type = (meta["type"] or "").lower()
    role = (meta["role"] or "").lower()
    is_react_select = role == "combobox" or bool(meta["rs"])

    T = 8000  # per-field cap so one stuck widget doesn't burn 30s
    if input_type == "file" or tag == "input" and input_type == "":
        from pathlib import Path as _P
        if _P(value).is_file():
            loc.set_input_files(value, timeout=T)
            return
    classes = (loc.get_attribute("class", timeout=3_000) or "").lower()
    if "candidate-location" in selector or "pac-target-input" in classes:
        _fill_places_autocomplete(page, loc, value, selector)
        return
    group_n = page.locator(_css(selector)).count()
    if input_type == "radio" or (input_type == "checkbox" and group_n > 1):
        _check_matching_in_group(page, selector, value, kind=input_type)
        return
    if tag == "select":
        _select_option_fuzzy(loc, value, selector)
    elif input_type == "checkbox":
        want = value.strip().lower() in {"yes", "true", "1", "on", "checked"}
        loc.set_checked(want, timeout=T)
    elif is_react_select:
        _fill_react_select(page, loc, value, selector)
    else:
        loc.fill(value, timeout=T)


def _fill_group_by_question(page, question: str, value: str) -> None:
    """Grouped control located by its question text: find the fieldset/container
    whose label matches, then click the option (radio label / checkbox / Yes-No
    button) that matches `value`. Never guesses — no match, left for the human."""
    from app.applications.standard_answers import _map_to_option

    q = " ".join(question.split())[:80]
    box = page.locator(
        "fieldset, [role=radiogroup], [role=group], [class*='fieldEntry'], [class*='form-field']"
    ).filter(has_text=q[:40]).first
    if box.count() == 0:
        box = page.locator(f"xpath=//*[contains(normalize-space(.), {_xpath_lit(q[:40])})][.//button or .//input]").last
    if box.count() == 0:
        raise RuntimeError(f"FILL_GROUP_NOT_FOUND:{q[:80]}")

    clickable = box.locator("label, [class*='_option'], button, [role=radio], [role=checkbox]")
    pairs = []
    for i in range(min(clickable.count(), 40)):
        el = clickable.nth(i)
        try:
            t = " ".join((el.inner_text(timeout=2000) or "").split())
        except Exception:
            t = ""
        if t:
            pairs.append((el, t))
    if not pairs:
        raise RuntimeError(f"FILL_GROUP_HAS_NO_OPTIONS:{q[:80]}")

    for wanted in ([value] if not _looks_multi(value) else re.split(r"[;,]", value)):
        wanted = wanted.strip()
        picked = _map_to_option(wanted, [t for _, t in pairs])
        if picked is None:
            raise RuntimeError(f"FILL_OPTION_NOT_FOUND:{q[:80]}")
        for el, t in pairs:
            if t == picked:
                inner = el.locator("input[type=radio], input[type=checkbox], [role=radio], [role=checkbox]").first
                if inner.count() and _try_check(page, inner):
                    pass
                else:
                    ok = False
                    for attempt in (lambda: el.click(timeout=4000),
                                    lambda: el.click(timeout=3000, force=True)):
                        try:
                            attempt(); ok = True; break
                        except Exception:
                            continue
                    if not ok:
                        raise RuntimeError(f"FILL_OPTION_NOT_CLICKABLE:{q[:80]}")
                break


def _looks_multi(value: str) -> bool:
    return ("," in value or ";" in value) and len(value) < 120


def _xpath_lit(s: str) -> str:
    if '"' not in s:
        return f'"{s}"'
    if "'" not in s:
        return f"'{s}'"
    return "concat('" + s.replace("'", "', \"'\", '") + "')"


def _check_matching_in_group(page, selector: str, value: str, *, kind: str) -> None:
    """Radio / checkbox group: check ONLY the option(s) whose label matches `value`.
    Never falls back to 'first' — a wrong EEO / veteran selection is worse than none."""
    from app.applications.standard_answers import _map_to_option

    inputs = page.locator(_css(selector))
    n = inputs.count()
    pairs = []  # (locator, label)
    for i in range(n):
        el = inputs.nth(i)
        try:
            label = el.evaluate(
                """el => {
                    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) return l.innerText; }
                    const w = el.closest('label'); if (w) return w.innerText;
                    const sib = el.nextElementSibling; if (sib && sib.innerText) return sib.innerText;
                    return el.getAttribute('aria-label') || el.value || '';
                }""",
                timeout=3_000,
            )
        except Exception:
            label = ""
        pairs.append((el, " ".join((label or "").split())))

    labels = [lbl for _, lbl in pairs]
    want_values = [value] if kind == "radio" else [v.strip() for v in re.split(r"[;,]", value) if v.strip()]
    checked_any = False
    for wv in want_values:
        picked = _map_to_option(wv, labels)
        if picked is None:
            print(f"  ! no {kind} option like '{wv}' for {selector} — left for you")
            continue
        for el, lbl in pairs:
            if lbl == picked:
                if _try_check(page, el):
                    checked_any = True
                else:
                    print(f"  ! {selector}: could not check '{picked}'")
                break
    if not checked_any and want_values:
        raise RuntimeError(f"FILL_OPTION_NOT_FOUND:{selector}")


def _try_check(page, el) -> bool:
    """Check a radio/checkbox that a custom ATS may have visually hidden."""
    for attempt in (
        lambda: el.check(timeout=4_000),
        lambda: el.check(timeout=3_000, force=True),
        lambda: el.click(timeout=3_000, force=True),
    ):
        try:
            attempt()
            return True
        except Exception:
            continue
    # last resort: click the label bound to its id
    try:
        eid = el.get_attribute("id", timeout=2_000)
        if eid:
            lab = page.locator(f'label[for="{eid}"]').first
            if lab.count():
                lab.click(timeout=3_000, force=True)
                return True
    except Exception:
        pass
    return False


def _select_option_fuzzy(loc, value: str, selector: str) -> None:
    from app.applications.standard_answers import _map_to_option
    options = loc.evaluate("el => [...el.options].map(o => o.textContent.trim()).filter(Boolean)")
    if not options:
        raise RuntimeError(f"FILL_SELECT_HAS_NO_OPTIONS:{selector}")
    try:
        loc.select_option(label=value)
        return
    except Exception:
        pass
    mapped = _map_to_option(value, options)
    if mapped is None:
        raise RuntimeError(f"FILL_OPTION_NOT_FOUND:{selector}")
    loc.select_option(label=mapped)


def _fill_places_autocomplete(page, loc, value: str, selector: str) -> None:
    """Greenhouse's #candidate-location and similar: type, then pick a suggestion."""
    try:
        loc.click(timeout=6000)
        loc.fill(value, timeout=6000)
    except Exception:
        raise RuntimeError(f"FILL_NOT_INTERACTABLE:{selector}")
    page.wait_for_timeout(900)
    for sel in ('.pac-item:visible', '[role="option"]:visible',
                'ul[role="listbox"] li:visible', '.dropdown-item:visible'):
        opts = page.locator(sel)
        if opts.count():
            opts.first.click(timeout=4_000)
            page.wait_for_timeout(150)
            return
    # no suggestions surfaced — leave the typed text, better than empty
    raise RuntimeError(f"FILL_AUTOCOMPLETE_UNCONFIRMED:{selector}")


def _fill_react_select(page, loc, value: str, selector: str) -> None:
    from app.applications.standard_answers import _map_to_option

    def read_options():
        opts = page.locator('[id^="react-select"][id*="option"], [role="option"]')
        return [(opts.nth(i), (opts.nth(i).inner_text() or "").strip()) for i in range(opts.count())]

    try:
        loc.click(timeout=6000)
    except Exception:
        raise RuntimeError(f"FILL_NOT_INTERACTABLE:{selector}")
    page.wait_for_timeout(300)
    texts = read_options()

    # First try to match against the UNFILTERED list (EEO / yes-no / small enums).
    def match(texts):
        labels = [t.split(" +")[0].strip() for _, t in texts]
        picked = _map_to_option(value, labels)
        if picked is not None:
            for el, t in texts:
                if t.split(" +")[0].strip() == picked:
                    return el
        return None

    target = match(texts)
    # Long or lazy list (country, school shows nothing until you type): filter, then match.
    if target is None and (len(texts) > 12 or len(texts) == 0):
        try:
            loc.fill(value)
        except Exception:
            try:
                loc.type(value, delay=10)
            except Exception:
                pass
        page.wait_for_timeout(450)
        texts = read_options()
        target = match(texts)
        if target is None and len(texts) == 1 and texts[0][1]:
            target = texts[0][0]

    if target is None:
        page.keyboard.press("Escape")
        raise RuntimeError(f"FILL_OPTION_NOT_FOUND:{selector}")
    target.click()
    page.wait_for_timeout(150)


def _css(selector: str) -> str:
    key, sep, val = selector.partition("=")
    if sep and key in {"id", "name", "data-testid", "aria-label"}:
        return f'[{key}="{val}"]'
    return selector


def _role_from_title(page_title: str, fallback: str) -> str:
    m = re.search(r"Job Application for (.+?) at .+$", page_title or "", re.I)
    return m.group(1).strip() if m else fallback


def _hash(pdf_path: str | None) -> str:
    if not pdf_path:
        return ""
    import hashlib
    return "sha256:" + hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("packet")
    pk.add_argument("--url", required=True)
    pk.add_argument("--company", required=True)
    pk.add_argument("--role", default="")
    pk.add_argument("--ats", choices=("greenhouse", "lever", "ashby"), default="greenhouse")
    pk.add_argument("--profile", default="config/candidate_profile.yaml")
    pk.add_argument("--resume-pdf")
    pk.add_argument("--out", required=True)
    pk.add_argument("--timeout-ms", type=int, default=30_000)
    pk.set_defaults(func=cmd_packet)

    fl = sub.add_parser("fill")
    fl.add_argument("--packet", required=True)
    fl.add_argument("--answers")
    fl.add_argument("--profile", default="config/candidate_profile.yaml")
    fl.add_argument("--resume-pdf")
    fl.add_argument("--headed", action="store_true")
    fl.add_argument("--keep-open-seconds", type=int, default=0,
                    help="with --headed, hold the browser open this long instead of waiting on Enter")
    fl.add_argument("--timeout-ms", type=int, default=30_000)
    fl.set_defaults(func=cmd_fill)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
