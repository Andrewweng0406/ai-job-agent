"""Playwright-native form scanner.

Reads the fields the browser actually rendered — including what a raw-HTML parser
misses on Ashby / custom ATS forms: Yes/No <button> pairs, checkbox groups in
plain <div>s, [role=radiogroup], date pickers, and forms with no <form> element.
Returns plain dicts so the rest of the pipeline (resolve -> standard answers ->
essay) is unchanged.

Grouped controls (radio / checkbox / Yes-No) get selector `q=<question text>`;
the filler locates the question's container and clicks the matching option.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_SCAN_JS = r"""
() => {
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const vis = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const FIELD = 'fieldset, [role=radiogroup], [role=group], [class*="fieldEntry" i], ' +
                '[class*="form-field" i], [data-field], [class*="question" i]';
  const explicitLabel = el => {
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return clean(lab.innerText || lab.textContent);
    }
    const labelledBy = clean(el.getAttribute('aria-labelledby'));
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map(id => document.getElementById(id))
        .filter(Boolean).map(n => clean(n.innerText || n.textContent)).join(' ');
      if (text) return text;
    }
    const aria = clean(el.getAttribute('aria-label'));
    if (aria) return aria;
    const wrapping = el.closest('label');
    if (wrapping) {
      const clone = wrapping.cloneNode(true);
      clone.querySelectorAll('input,select,textarea,button').forEach(n => n.remove());
      const text = clean(clone.innerText || clone.textContent);
      if (text) return text;
    }
    return '';
  };
  const optLabel = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    const w = el.closest('label'); if (w) return clean(w.innerText);
    const p = el.parentElement;
    if (p && clean(p.innerText)) return clean(p.innerText);
    return clean(el.getAttribute('aria-label') || el.value || '');
  };
  const questionOf = el => {
    const direct = explicitLabel(el);
    if (direct) return direct;
    const box = el.closest(FIELD);
    if (box) {
      const lab = box.querySelector(':scope > label, :scope > legend, :scope > [class*="label" i], :scope > div, :scope > p, :scope > span');
      if (lab) {
        // the label node, not an option row
        const t = clean(lab.innerText);
        if (t && t.length <= 280 && !lab.querySelector('input, button')) return t;
      }
      const first = clean(box.innerText).split('\n')[0];
      if (first && first.length <= 280) return first;
    }
    // generic: nearest previous heading/label-ish text
    let n = el;
    for (let i = 0; i < 6 && n; i++) {
      n = n.parentElement; if (!n) break;
      const c = n.querySelector(':scope > label, :scope > legend, :scope > p, :scope > [class*="label" i], :scope > [class*="title" i]');
      if (c && clean(c.innerText) && !c.querySelector('input,button') && clean(c.innerText).length < 280) return clean(c.innerText);
    }
    return clean(el.getAttribute('placeholder') || el.name || el.id || '');
  };
  const nameSel = el => el.id ? 'id=' + el.id : (el.name ? 'name=' + el.name :
                  (el.getAttribute('data-testid') ? 'data-testid=' + el.getAttribute('data-testid') : ''));
  const requiredOf = (el, q) => el.required || el.getAttribute('aria-required') === 'true' || /\*/.test(q || '');

  const out = [];
  const doneGroup = new Set();
  const push = f => { if (f.label && f.selector) out.push(f); };

  const controls = [...document.querySelectorAll(
    'input, select, textarea, [role=radio], [role=checkbox], [role=combobox]'
  )].filter(vis).filter(el => {
    const t = (el.getAttribute('type') || '').toLowerCase();
    return !['hidden', 'submit', 'button', 'reset', 'search'].includes(t);
  });

  for (const el of controls) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const isRadio = type === 'radio' || role === 'radio';
    const isCheck = type === 'checkbox' || role === 'checkbox';

    if (isRadio || isCheck) {
      const q = questionOf(el);
      const box = el.closest(FIELD);
      const gkey = (box ? (box.className + '|' + q) : (el.name || q)) + '|' + (isCheck ? 'c' : 'r');
      if (doneGroup.has(gkey)) continue;
      doneGroup.add(gkey);
      let peers = [];
      if (box) peers = [...box.querySelectorAll('input[type=' + (isCheck ? 'checkbox' : 'radio') + '], [role=' + (isCheck ? 'checkbox' : 'radio') + ']')];
      else if (el.name) peers = [...document.querySelectorAll(`[name="${CSS.escape(el.name)}"]`)];
      else peers = [el];
      peers = peers.filter(vis);
      const opts = [...new Set(peers.map(optLabel).map(clean).filter(Boolean))];
      if (opts.length < 1) continue;
      const names = [...new Set(peers.map(p => p.name).filter(Boolean))];
      const sel = names.length === 1 ? ('name=' + names[0]) : ('q=' + q);
      push({ label: q, kind: isCheck ? 'checkbox_group' : 'radio_group',
             selector: sel, required: peers.some(p => requiredOf(p, q)), options: opts });
      continue;
    }

    if (el.tagName === 'SELECT') {
      push({ label: questionOf(el) || nameSel(el), kind: 'select', selector: nameSel(el),
             required: requiredOf(el, ''), options: [...el.options].map(o => clean(o.textContent)).filter(Boolean) });
      continue;
    }
    if (role === 'combobox' || el.closest('[class*="select__" i], [class*="-control" i]')) {
      push({ label: questionOf(el), kind: 'combobox', selector: nameSel(el), required: requiredOf(el, ''), options: [] });
      continue;
    }
    if (el.tagName === 'TEXTAREA') {
      push({ label: questionOf(el), kind: 'long_text', selector: nameSel(el), required: requiredOf(el, ''), options: [] });
      continue;
    }
    const q = questionOf(el);
    let kind = 'text';
    if (type === 'file') kind = 'file';
    else if (type === 'number') kind = 'numeric';
    else if (type === 'date' || /\bdate\b/i.test(q) || el.getAttribute('placeholder') === 'Pick date...') kind = 'date';
    push({ label: q, kind, selector: nameSel(el), required: requiredOf(el, q), options: [] });
  }

  // Yes/No <button> pairs (Ashby boolean questions)
  const seenBtnQ = new Set();
  const btns = [...document.querySelectorAll('button, [role=button]')].filter(vis)
    .filter(b => /^(yes|no|true|false)$/i.test(clean(b.innerText)));
  for (const b of btns) {
    const box = b.closest(FIELD);
    const q = box ? questionOf(b) : '';
    if (!q || seenBtnQ.has(q)) continue;
    seenBtnQ.add(q);
    const opts = box ? [...new Set([...box.querySelectorAll('button, [role=button]')]
        .map(x => clean(x.innerText)).filter(t => /^(yes|no|true|false)$/i.test(t)))] : ['Yes', 'No'];
    if (opts.length >= 2) push({ label: q, kind: 'button_choice', selector: 'q=' + q, required: /\*/.test(q), options: opts });
  }
  return out;
}
"""


@dataclass(frozen=True, slots=True)
class ScannedField:
    label: str
    kind: str
    selector: str        # id=… | name=… | data-testid=… | q=<question text>
    required: bool
    options: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "kind": self.kind, "selector": self.selector,
                "required": self.required, "options": list(self.options)}


def scan_form(page) -> list[ScannedField]:
    raw = page.evaluate(_SCAN_JS)
    fields: list[ScannedField] = []
    seen: set[str] = set()
    for item in raw or []:
        label = (item.get("label") or "").strip()
        selector = (item.get("selector") or "").strip()
        selector_lower = selector.lower()
        if label.lower() in {"attach", "upload", "choose file"}:
            if "resume" in selector_lower or "cv" in selector_lower:
                label = "Resume/CV"
            elif "cover" in selector_lower:
                label = "Cover Letter"
        if not label or not selector or selector in {"q=", "id=", "name="}:
            continue
        key = f"{selector}\0{item.get('kind')}"
        if key in seen:
            continue
        seen.add(key)
        fields.append(ScannedField(
            label=label[:280],
            kind=str(item.get("kind") or "text"),
            selector=selector,
            required=bool(item.get("required")),
            options=[str(o) for o in (item.get("options") or []) if str(o).strip()][:60],
        ))
    return fields
