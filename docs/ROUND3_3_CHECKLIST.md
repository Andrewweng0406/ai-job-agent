# ROUND3_3_CHECKLIST.md — Final Greenhouse Gate G Audit

**Author:** Claude (reviewer)
**Reviewed at:** HEAD = `60985ce` (my Round 3.2 commit). **No Phase 4.3 follow-up exists** — the newest
Codex commit is `9088c37`; nothing has been pushed since that addresses P1-28 / P2-21 / P2-22.
**Suite:** `pytest -q` → **392 passed, 1 skipped, 4 xfailed, 0 failed**.
**Rule:** the evidence bundle proves Gate G, not the test count. `real_submission_enabled` stays `false`.

---

## 1. Current HEAD / suite
`git log`: `60985ce` (Claude R3.2) ← `9088c37` (Codex, post-fill hard stop only) ← `dc766fc` (first live
run). Tree clean. `origin/main` == local. Suite green. The mission brief's "Codex: 9088c37 + Phase 4.3
follow-up" — **the follow-up is not in the repo.** This audit is therefore of the same code + evidence
as Round 3.2.

## 2. P1-28 lease fencing — **FAIL (still absent)**
`app/applications/greenhouse_live.py` (unchanged since Round 3.2; `9088c37` only added the post-fill
re-capture). `GreenhouseLiveDryRunRunner.run()` contains **no** `lease_still_mine` / `worker_id` /
`lease_epoch` reference. `self.autofill.apply(page, adapter_result.dry_run.resolutions, …)` iterates
every resolution and mutates the live page with **zero** lease checks before nav, after nav, before
fill, mid-fill, before/after upload, or before persistence. A lost lease produces no abort. There is no
`browser_actions` log to inspect ordering/worker identity against (P2-22).

## 3. P1-28 approval gate — **FAIL (still absent)**
`grep ApprovedAutofillPreviewBuilder|approved_by|approved_at` over `greenhouse_live.py` +
`browser_autofill.py` → **no match.** The live autofill runs from `adapter_result.dry_run.resolutions`
(the transcript just built this call), never checked against approval, `payload_hash`, resume-hash, or
answer-bank tampering. `payload.human_invoked=True` is the **only** gate — the brief explicitly says
that alone is insufficient. Unapproved / expired-approval / tampered-payload / changed-resume-hash /
changed-answers all currently drive live fill.

## 4. P2-21 hidden/honeypot exclusion — **PARTIAL (unchanged)**
`_is_noninteractive` still only catches `aria-hidden="true"`, `tabindex="-1"`, `style` with
`display:none` / `visibility:hidden`. Missed: bare `hidden` attr, `disabled`, `type` unset offscreen
(`position:absolute;left:-9999px`), `opacity:0`, `height:0`/`width:0`.
`tests/test_round32_regressions.py::test_other_hidden_field_techniques_are_also_excluded` (xfail).

## 5. Reproduce live run — **NO SCRIPT; reviewer did an independent read-only navigation**
`scripts/` is **empty** — there is no `scripts/live_dry_run.py` or equivalent. Codex's run is not
reproducible from the repo.
**Independent check (reviewer, read-only, no app code, no interaction beyond `goto` + `content`):**
navigated `https://job-boards.greenhouse.io/anthropic/jobs/4461450008` with headless Chromium
(Playwright 1.61.0):
- HTTP **200**, final URL unchanged, title **"Job Application for Account Executive, AI Native at
  Anthropic"**, `len(html) ≈ 106 KB`.
- **1 `<form>`, 29 `<input>`, 3 `<textarea>`**; HTML contains `first_name`, `last_name`, `resume`,
  `sponsorship`, `authoriz`, `submit application`, `greenhouse`, `account executive`.
- ⇒ The page Codex navigated in `dc766fc` **was genuinely a real, live Greenhouse application form.**
  Navigation authenticity: **CONFIRMED independently.**

## 6. Artifact bundle completeness — **FAIL**
`artifacts/` contains exactly **one file**: `greenhouse_anthropic_4461450008.png`.
Missing every other required artifact: `report.json` (only a hand-writable aggregate lives at
`docs/greenhouse_live_dry_run_report.json`), `dom.sanitized.html`, `field_map.json`,
`browser_actions.jsonl`, `safety.json`, `transcript.sanitized.json`, `before_fill.png`,
`after_fill.png`. No `run_id`, no ISO `captured_at`, no lease metadata, no approval metadata.

## 7. DOM authenticity — **page is real (reviewer-verified); Codex's DOM capture does not exist**
No `dom.sanitized.html` was archived, so Codex's *extraction artifact* cannot be checked. The *page*
is real (see §5). Source metadata / sanitized marker: absent.

## 8. Field traceability — **CANNOT PERFORM**
No `field_map.json`, no captured DOM. `docs/greenhouse_live_dry_run_report.json` gives only aggregates
(24 discovered / 3 auto-safe / 14 profile-or-human / 7 optional-skip). Zero fields can be traced to a
DOM element with raw label / type / required / options / normalized mapping.

## 9. Excluded-honeypot audit — **CANNOT PERFORM**
No field map, no transcript export, no browser-action log. Cannot confirm whether any hidden control on
the live Anthropic form entered the autofill set. (Code-level: `_is_noninteractive` would miss several
techniques — §4.)

## 10. Screenshot audit — **FAIL (JD fold only)**
`greenhouse_anthropic_4461450008.png` (1280×720) shows the **job-description fold** — logo, title,
"About Anthropic" / "About the role". It does **not** show the application-form region, nor a
before-fill / after-fill pair. No candidate data visible (nothing to leak — profile is TODO). Does not
satisfy §10.

## 11. Browser-action log audit — **CANNOT PERFORM** (no `browser_actions.jsonl`).
Code-level: `press("Enter")` / `Return` / `requestSubmit` / `form.submit()` / submit-event / submit-click
are absent from `browser_autofill.py` + `greenhouse_live.py` (verified Round 3.2 + re-verified). But an
action log for the actual run does not exist.

## 12. Transcript ↔ browser diff — **CANNOT PERFORM as an artifact**
`DryRunBrowserAutofill.apply` runs a live `BROWSER_TRANSCRIPT_MISMATCH` check **in code** (re-reads each
field post-fill; raises on divergence). But nothing from the `dc766fc` run captured planned vs attempted
vs read-back values, so `mismatch_count` / `unplanned actions` cannot be independently confirmed for the
run.

## 13. Lease-token trace — **CANNOT PERFORM** (no lease in the live path — §2; no action log).

## 14. Approval trace — **CANNOT PERFORM** (no approval in the live path — §3; no approval metadata in
any artifact).

## 15. Post-fill hard stop — **PRESENT in code, not evidenced for the run**
`greenhouse_live.py:113-125` re-captures after `autofill.apply` and, if `post_fill.human_required`,
persists the hard stop and returns `HUMAN_REQUIRED`. `report.json` says `captcha_or_bot_wall: false`, so
on this run the branch was not taken — no artifact proves the re-capture executed.

## 16. Resume status — **N/A, truthfully reported — PASS**
`resume_upload_call_count: 0`. Profile is TODO-backed ⇒ résumé field resolved `HUMAN_REQUIRED` ⇒ no
upload attempted. Report states this plainly; no overclaim.

## 17. Submission safety — **explicit count 0; no implicit vector in code**
`final_submit_invocation_count: 0`. Code inspection (Round 3.2 + re-verified): no `press("Enter")`,
`form.submit()`, `requestSubmit()`, submit-button click, or submit-event dispatch anywhere in
`browser_autofill.py` / `greenhouse_live.py` / `ats_dom_dry_run.py`. `GreenhouseLiveDryRunRunner`
refuses `real_submission_enabled=True` before navigating. **But** the autofill path is unfenced (§2) and
unapproved (§3), so a *future* misuse (e.g. concurrent worker, tampered transcript) is not structurally
prevented.

## 18. PII / secret audit — **PASS**
Committed artifacts: `artifacts/greenhouse_anthropic_4461450008.png` (Anthropic JD only) +
`docs/greenhouse_live_dry_run_report.json` (aggregates + a payload hash + a transcript uuid). No email,
phone, address, cookie, token, session id, or résumé text. `config/candidate_profile.yaml` still 20×
`TODO`. Clean.

## 19. Gate G decision

| Requirement | Status |
|---|---|
| real navigation | ✔ (reviewer-verified, §5) |
| real DOM capture | ✘ no `dom.sanitized.html` |
| traceable field map | ✘ no `field_map.json` |
| safe hidden-field exclusion | ~ partial (P2-21) |
| lease-fenced autofill | ✘ (§2) |
| approved transcript | ✘ (§3) |
| action log | ✘ (§6/§11) |
| post-fill safety check | ~ in code, not evidenced (§15) |
| transcript/browser diff = 0 | ~ in code, no run artifact (§12) |
| submit risk absent | ✔ code; ~ structurally (unfenced/unapproved) |
| artifact bundle complete | ✘ (§6) |
| PII-safe evidence | ✔ (§18) |

**Gate G — FAIL.** Multiple core requirements unmet: no DOM capture, no field map, no action log, no
lease fencing, no approval gate, incomplete bundle. Real navigation is now independently confirmed, but
that is one requirement of many.

## New P0
**None.**

## New P1
- **P1-28 (still open, both halves)** — live-autofill path has neither lease fencing nor an
  approved-transcript gate. `human_invoked=True` is the sole guard.

## Remaining P2/P3 (carried)
- **P2-21** — broaden `_is_noninteractive` (`hidden` attr, `disabled`, offscreen, `opacity:0`).
- **P2-22** — no reproducible `scripts/live_dry_run.py` and no archived artifact bundle
  (`report.json` + `dom.sanitized.html` + `field_map.json` + `browser_actions.jsonl` + `safety.json` +
  `transcript.sanitized.json` + before/after form screenshots + `run_id` + ISO `captured_at`).

---

## May Codex proceed to Lever / Ashby?
**No.** Gate G is not closed. Blockers: P1-28 (lease + approval), P2-21, P2-22. Lever/Ashby share
`AtsDomDryRunAdapter` + `HtmlFormFieldExtractor` + (for a future live path) the same runner shape — every
finding transfers.

## Remaining blockers before controlled real submission
1. **P1-28** — lease-fence the live-autofill path (`lease_still_mine` before nav, before fill, per-field
   or per-batch, before upload, before persistence) **and** require a valid `ApprovedAutofillPreviewBuilder`
   transcript (approval not expired; `payload_hash` matches; resume hash matches; answer bank matches).
2. **P2-22** — commit `scripts/live_dry_run.py`; on each run archive `artifacts/<run_id>/` with
   `report.json`, `dom.sanitized.html` (with `captured_at`, `source_url`, `final_url`, `page_title`,
   `sanitized: true`), `field_map.json` (per field: selector, raw_label, type, required, options,
   canonical_key, policy, resolved_value/status, dom_xpath), `browser_actions.jsonl` (ordered, with
   worker_id + lease_epoch), `safety.json` (submit_invocation_count, implicit-risk scan result,
   post-fill hard-stop result, mismatch_count), `transcript.sanitized.json`, `before_fill.png` +
   `after_fill.png` of the **form region**.
3. **P2-21** — hidden-field exclusion for the remaining techniques.
4. Re-run this checklist (§5–§18) against the archived bundle; Gate G can PASS only when every §19 row is ✔.
5. `real_submission_enabled` stays `false` until ≥3 fully-archived, independently-audited dry-run bundles
   per ATS.
