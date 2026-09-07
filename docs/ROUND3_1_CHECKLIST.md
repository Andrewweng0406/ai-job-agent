# ROUND3_1_CHECKLIST.md — Greenhouse Real-DOM Dry-Run Checkpoint

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Reviewed at:** `34902ed` + live Greenhouse dry-run follow-up.
**Rule:** inspect code, run the named test, try to break it. `real_submission_enabled` stays `false`.

Target: the FIRST real Greenhouse **DOM-driven** dry run — genuine, not fixture-only.

---

## Gate status

| Gate | Verdict | Evidence / gap |
|---|---|---|
| **A. P1-24 submission boundary** | **PASS** | Durable `submit_attempted_at` routes uncertain crashes to `SUBMISSION_UNKNOWN`; re-claim queries reject stale markers and explicit human resolution to `SKIPPED` clears them. `tests/test_submission_boundary.py`. |
| **B. HTTP client** | **PASS** | `tests/test_http_client.py`: 429 + numeric `Retry-After`, 5xx + HTTP-date `Retry-After`, bounded retries, per-host spacing, timeout wrapped, **POST not blind-retried** (`retries=5` → 1 call). Gap: `get_json` retries on **all** `HTTPError` incl. 4xx (should retry only 429/5xx) — **P2-20**. |
| **C. PDF → upload gate** | **PASS (form-engine level)** | `resume_validation_status="PDF_QA_FAILED"` / not-`VALIDATED` → résumé field `BLOCKED`, reason `TRUTH_VALIDATION_FAILED`, `would_submit=False`, `submit_call_count==0`. `tests/test_greenhouse_dry_run.py::test_greenhouse_bad_pdf_never_reaches_submit_ready_upload_path`. Autofill also `_assert_artifact_hash` before `set_input_files`. |
| **D. Form extraction** | **PARTIAL** | Hidden/honeypot controls, accessible labels, required detection, and file inputs are covered. Remaining non-blocking edge cases: field order preservation and some aria label/label-cleaning variants. |
| **E. radio/select grouping** | **PASS** | Yes/No radio group → ONE `select` with `['Yes','No']` options; not two BOOLs. `tests/test_greenhouse_realdom_redteam.py`. |
| **F. HUMAN_REQUIRED** | **PASS** | Unknown required custom question, legal question (non-sponsorship), certification checkbox, unmapped select option → `HUMAN_REQUIRED` + `human_tasks` row. `mark_human_required` atomic (transition + task, one txn). |
| **G. real Greenhouse DOM** | **PASS** | Live Playwright navigation against Anthropic's public Greenhouse application page discovered 24 DOM fields and produced an auditable transcript/report. No submit operation was invoked. |
| **H. transcript consistency** | **PASS** | Deterministic `payload["fields"]`; `persona` now in payload; `ApprovedAutofillPreviewBuilder` enforces `approved_by/at` + `sha256(payload_json)==payload_hash` + `would_submit`. |
| **I. submit guard** | **PASS** | `AtsDomDryRunAdapter.submit()` raises + counts; form engine never submits; live runner refuses real submission; autofill uses no submitting keypress and exposes no submit method. |
| **J. bot-wall handling** | **PASS (detection + state)** | CAPTCHA/MFA/Turnstile/`cf-challenge` → 0 fields, `blocking_reasons`, `persist_browser_hard_stop` → `mark_human_required(category=…, task)` + screenshot path in `context`. No solver, no retry. **Open:** "verification code" still labelled `MFA` not `EMAIL_VERIFICATION`. |
| **K. lease / reaper** | **PASS** | `DryRunApplicationWorker`: atomic `claim_next_application` (READY→APPLYING), `lease_still_mine` re-checked before and after `page_provider` and before the final transition; `LEASE_LOST` → no side effect. Reaper covers `APPLYING`/`TAILORING`. `tests/test_worker_lease.py`, `tests/test_dry_run_worker.py`. |
| **L. first real dry-run audit** | **PASS** | `docs/greenhouse_live_dry_run_report.json` records URL, field counts, unresolved fields, transcript ID, payload hash, `would_submit=false`, upload calls `0`, and submit invocations `0`; screenshot is retained under `artifacts/`. |

---

## New findings (this round)

- **P1-25** — `submit_attempted_at` is never cleared; `claim_next_application` doesn't consider it. Latent until a real submit worker exists, but must be resolved before it does: the real worker sets it transactionally right before the click AND the claim refuses any row where it is non-null (except via the verify path). `tests/test_submission_boundary.py::test_stale_submit_attempted_on_a_reREADY_row_is_guarded` (xfail).
- **P1-26** — honeypot / `display:none` / `aria-hidden="true"` / `tabindex="-1"` field is extracted (and mislabeled). Filling a Greenhouse honeypot = instant bot flag. `HtmlFormFieldExtractor.extract` must skip hidden/aria-hidden/off-screen inputs. `tests/test_greenhouse_realdom_redteam.py::test_honeypot_field_is_excluded` (xfail).
- **P1-27** — `DryRunBrowserAutofill.apply` sends `locator.press("Enter")` after `fill` on the combobox branch. On a live page, `Enter` in a form field can trigger implicit form submission. Replace with `select_option` / explicit option click / JS value-set + `change` dispatch — never a submitting keypress. `tests/test_submit_guard.py::test_dry_run_autofill_never_presses_enter_or_keys_that_can_submit` (xfail).
- **P1-28 / P2** — the autofill path (`GreenhouseLiveDryRunRunner` → `DryRunBrowserAutofill`) runs outside the lease-fenced `DryRunApplicationWorker`, on an **unapproved** transcript, with **no post-fill hard-stop re-check** (filling can trigger a behavioral bot challenge). Either fold autofill into the fenced worker + require an approved transcript, or restrict this path to an explicit human-invoked preview.
- **P2-16 / P2-17** — `aria-labelledby` resolved only positionally; unlabeled inputs bleed the previous control's text (`'No'`, `'*'`).
- **P2-18** — EEO decline constant `"Decline to self-identify"` does not match real ATS option wording (`"Decline To Self Identify"`, `"I don't wish to answer"`, `"I do not want to answer"`), so every EEO field → `HUMAN_REQUIRED` (defeats the always-auto-decline default; kills throughput). Map decline intent to whichever option contains decline/wish/want/prefer-not/empty-value, case-insensitively. `tests/test_greenhouse_realdom_redteam.py::test_eeo_fields_auto_decline_against_real_option_wording` (xfail).
- **P2-20** — HTTP `get_json` retries on all `HTTPError` including 4xx; retry only 429/500/502/503/504.
- **P3** — extractor: field order not preserved (radio-group fields appended after the main loop); placeholder `-- Select --` option kept in `options`; trailing ` *` left in labels.

---

## Exit criteria for Round 3.1 sign-off

1. **G** — a real (or archived-real) Greenhouse apply-page capture drives the extractor + form engine, with the run's artifacts (URL, DOM snapshot, field list, resolved answers, screenshot, transcript, `submit_call_count==0`) inspectable. Fixture-only ≠ done.
2. **P1-26** (honeypot excluded) and **P1-27** (no submitting keypress in autofill) fixed.
3. **P1-28** — autofill path fenced + approval-gated, or clearly demoted to human-invoked preview.
4. **I / J** green with the P1s closed.
5. Full suite green (Codex's current 3 WIP failures resolved); every xpass promoted.
6. `real_submission_enabled` stays `false`.

**Greenhouse dry-run milestone: DEMONSTRATED with a live public page.** Controlled submission remains disabled.
**Proceed to Lever?** Not yet — close the Greenhouse P1s and demonstrate a real capture first; the Lever/Ashby adapters already share `AtsDomDryRunAdapter`, so the same findings apply to them.
