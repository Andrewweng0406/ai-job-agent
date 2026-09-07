# ROUND3_2_CHECKLIST.md — Verify the First Provable Live Greenhouse Run

**Author:** Claude (reviewer)
**Reviewed at:** `dc766fc` ("Complete first live Greenhouse dry run"). Worktree **clean**.
**Suite:** `pytest -q` → **392 passed, 1 skipped, 4 xfailed** (xfails = P2-21). No failures.
**Rule:** the evidence bundle proves Gate G, not the test count. `real_submission_enabled` stays `false`.

---

## 1. Worktree / suite
Clean tree at `dc766fc`. Codex's 3 prior WIP failures are resolved. Full suite green.
Candidate profile still 20× `TODO`; `config/settings.yaml → real_submission_enabled: false`. ✔

## 2. P1-25 — submit-attempt reclaim guard — **PASS**
`claim_next_application` WHERE clause now includes `AND submit_attempted_at IS NULL` for both `READY` and
`RETRY_PENDING`. `transition_application` clears the marker **only** on `→ SKIPPED`
(`CASE WHEN ? = 'SKIPPED' THEN NULL ELSE submit_attempted_at END`). `reap_expired_leases` routes
`APPLYING`+marker → `SUBMISSION_UNKNOWN`. Verified: a row carrying the marker cannot be claimed from
`READY` or `RETRY_PENDING`; only an explicit human `→ SKIPPED` clears it.
`tests/test_round32_regressions.py::test_row_with_submit_marker_cannot_be_claimed_*`.

## 3. P1-26 — hidden / honeypot exclusion — **PARTIAL (→ P2-21)**
`_is_noninteractive` skips `aria-hidden="true"`, `tabindex="-1"`, `style` with `display:none` /
`visibility:hidden`. The common Greenhouse honeypot (`display:none` + `aria-hidden`) is now excluded, and
legitimate controls are not dropped. **Still missed:** bare `hidden` attribute, `disabled` inputs
(disabled trap), offscreen decoys (`position:absolute;left:-9999px`), `opacity:0` / `height:0`.
`tests/test_round32_regressions.py::test_other_hidden_field_techniques_are_also_excluded` (xfail).

## 4. P1-27 — no implicit-submission interaction — **PASS**
`locator.press("Enter")` removed from `browser_autofill.py` (combobox branch now `fill()` only).
grep of `browser_autofill.py` + `greenhouse_live.py` + `ats_dom_dry_run.py` for `press(`, `Enter`,
`Return`, `requestSubmit`, `.submit()`, `dispatch…submit`, `keyboard.press` → none.
`DryRunBrowserAutofill` exposes no submit method; `AtsDomDryRunAdapter.submit()` raises.
`tests/test_round32_regressions.py::test_no_submitting_keypress_in_browser_or_autofill_path`.
*Residual:* an ARIA combobox filled without a commit action may not register the choice — but the
post-fill differential (`BROWSER_TRANSCRIPT_MISMATCH`) then raises, so it fails closed.

## 5. P1-28 — lease fencing + approval gate for live autofill — **PARTIAL (still open)**
**Improved:** `payload.autofill and not payload.human_invoked` → raises
`"Live autofill requires explicit human_invoked=True"`; after `autofill.apply` the runner re-captures
the page and, if `post_fill.human_required`, persists the hard stop and returns `HUMAN_REQUIRED`
(**§6 post-fill bot-wall — PASS**).
**Still missing:**
- **No lease fencing.** `GreenhouseLiveDryRunRunner` performs zero `lease_still_mine` checks;
  `autofill.apply` loops every resolution with no lease re-check between fields. The lease-fenced
  `DryRunApplicationWorker` calls the adapters directly, not this runner — the live autofill path is
  outside any lease. "Lease expires mid-fill → no further browser mutations" is not enforced.
- **No approved-transcript check.** It drives autofill from `adapter_result.dry_run.resolutions`
  directly; `ApprovedAutofillPreviewBuilder` (which checks `approved_by/at` + `payload_hash` +
  `would_submit`) is a different, unused path. `human_invoked=True` ≠ approved transcript.

## 6. Post-fill hard stop — **PASS** (see §5).

## 7. P2-18 — EEO safety — **PASS**
`_map_select_value` has an `eeo_decline` branch matching options containing
`decline | prefer not | wish | want`. Verified against "Decline To Self Identify", "Prefer not to
answer", "I do not wish to disclose", "Choose not to answer", "I don't wish to self-identify". A field
with **no** safe decline option is not `FILLED` with a real demographic value.
`tests/test_round32_regressions.py::test_eeo_decline_maps_to_a_safe_option`,
`::test_eeo_never_selects_a_real_demographic_value`.

## 8. P2-20 — HTTP 4xx not retried — **PASS**
`retryable_status = exc.code == 429 or exc.code in {500,502,503,504}`; otherwise raise immediately.
400 / 401 / 403 / 404 / 422 → exactly 1 call each; 429 retried. POST still `retry=False` → 1 call.
`tests/test_round32_regressions.py::test_http_client_does_not_retry_4xx`, `tests/test_http_client.py`.

## 9. Live-navigation authenticity — **REAL navigation, evidenced by the screenshot**
`artifacts/greenhouse_anthropic_4461450008.png` is a genuine 1280×720 render of
`https://job-boards.greenhouse.io/anthropic/jobs/4461450008` — real "A\" logo, real title
"Account Executive, AI Native", real "New York City, NY; San Francisco, CA", real "About Anthropic" /
"About the role" copy, "Apply" button. A real browser navigated a real, current Greenhouse page.
The code path (`sync_playwright()` → `chromium.launch` → `page.goto` → `page.content()`) is genuine.

## 10. Live-derived fixture authenticity — **FAIL — no archived capture**
There is **no sanitized DOM/HTML capture** from the run. No `captured_at`, no `source` marker, no
`sanitized` marker, no archived field structure. `tests/fixtures/ats_forms/greenhouse_application.html`
is the reviewer's hand-authored representative fixture (explicitly labelled "NOT a live capture"), not
derived from the run. **Gate G's §10 requirement is not met.**

## 11. Field-origin audit — **CANNOT PERFORM**
`docs/greenhouse_live_dry_run_report.json` gives only aggregate counts (24 discovered, 3 auto-safe,
14 profile/human-required, 7 optional-skipped). There is **no field map**, no per-field raw label /
element / required flag / options / type, and no captured DOM to trace against. The transcript
(`dry_6b531f0a…`) lives in a git-ignored `*.sqlite3`; the `payload_hash` in the report is unverifiable.

## 12. Browser-action audit — **CANNOT PERFORM**
No `browser_actions.log`. The report says `human_invoked_autofill: true` and
`resume_upload_call_count: 0`, `final_submit_invocation_count: 0`, but there is no per-action record of
which selectors were filled with which values, so the planned-vs-attempted diff cannot be independently
checked. (`DryRunBrowserAutofill` *does* run a live `BROWSER_TRANSCRIPT_MISMATCH` check in code — but
that is not captured in an artifact for this run.)

## 13. Resume upload — **not performed** (correctly stated)
`resume_upload_call_count: 0`. The profile is `TODO`-backed, so the résumé field resolved to
`HUMAN_REQUIRED` and no upload was attempted. The report states this. No "upload prepared" overclaim.

## 14. Lease safety — **PASS for the worker path, N/A for the live-run path**
`DryRunApplicationWorker` re-checks `lease_still_mine` before/after navigation and before the final
transition; reaper covers `APPLYING`/`TAILORING`. The live run used `GreenhouseLiveDryRunRunner`
directly (no lease) — see §5.

## 15. Submit implicit-risk audit — **explicit count 0; implicit path effectively closed**
`final_submit_invocation_count: 0`. `press("Enter")` removed (§4). No `form.submit()` / `requestSubmit()`
/ submit-button click / submit-event dispatch anywhere in the browser path. The autofill has no submit
surface and the live runner refuses `real_submission_enabled=True` before navigating. No residual
implicit-submission vector found in the current code.

## 16. Artifact bundle quality — **INSUFFICIENT**
Present: `report.json` (aggregate, hand-writable) + 1 screenshot (JD fold only, not the form).
Missing: sanitized DOM/HTML, field map, browser action log, safety report, form-region screenshot,
ISO `captured_at`, `run_id`. **No candidate PII / secrets committed** — clean.

## 17–18. New findings
- **P2-21** — `_is_noninteractive` misses bare `hidden` attr, `disabled`, offscreen (`left:-9999px`),
  `opacity:0`. Extend it before real autofill runs against arbitrary boards.
- **P2-22** — the first "live run" is a **manual, non-reproducible one-off**: no committed script,
  `test_greenhouse_live.py` still mocks, nothing in CI exercises a real navigation, and the run's
  artifacts (DOM, field map, action log) were never archived. A `scripts/live_dry_run.py` +
  `artifacts/<run_id>/{report.json,dom.sanitized.html,field_map.json,browser_actions.jsonl,safety.json,*.png}`
  bundle is needed to make Gate G auditable and repeatable.
- **P1-28 remains open** (fencing + approval gate for the live-autofill path) — see §5.

### New P0
**None.**

### New P1
- **P1-28 (still open)** — live-autofill path is unfenced and drives from an unapproved transcript.

---

## Gate G verdict — **FAIL (not independently evidenced)**

| Gate G part | Evidenced? |
|---|---|
| Real current Greenhouse page | ✔ (screenshot) |
| Real browser navigation | ✔ (screenshot + genuine Playwright code path) |
| Real DOM | ~ (24 fields reported, but no DOM archived to verify) |
| Real field extraction | ~ (no field map, no per-field trace) |
| Safe plan | ✔ (form-engine tests) |
| Safe dry-run interaction | ✔ (P1-27 fixed; post-fill hard stop; differential check in code) |
| No submission | ✔ (`final_submit_invocation_count: 0`; no implicit vector) |
| **Reviewable evidence** | ✘ (no sanitized DOM, field map, or action log; report + 1 screenshot only) |

Real navigation happened. The **auditable evidence bundle Gate G requires does not exist**, so §10/§11/§12
cannot be performed. **Gate G is not closed.**

## May Codex proceed to Lever?
**No.** Close P1-28 (fence + approval-gate the live-autofill path), land P2-21 (broader hidden-field
exclusion), and produce a repeatable live-run script + full archived artifact bundle (P2-22) so the
Greenhouse run is independently auditable. Lever/Ashby share `AtsDomDryRunAdapter` +
`HtmlFormFieldExtractor`, so every finding here transfers to them.

## Remaining blockers before controlled real submission
1. P1-28 — lease-fence + approval-gate the live-autofill path.
2. P2-21 — hidden/honeypot exclusion for `hidden`/`disabled`/offscreen/`opacity:0`.
3. P2-22 — reproducible live-run script + archived `report.json` + sanitized DOM + field map + browser
   action log + safety report + form screenshot + ISO `captured_at` + `run_id`.
4. A real submit worker still does not exist; when it lands it must set `submit_attempted_at`
   transactionally pre-click (the claim already refuses rows that carry it — P1-25 ✔).
5. `EMAIL_VERIFICATION` vs `MFA` labelling is now split ✔; verify the hard-stop task category flows
   through end to end.
6. `real_submission_enabled` stays `false` until ≥3 fully-archived, reviewed dry-run bundles per ATS.
