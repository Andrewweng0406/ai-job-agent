# ROUND3_4_CHECKLIST.md — Greenhouse Gate G re-audit (reproducible evidence bundle)

**Author:** Claude (reviewer, autonomous mode)
**Reviewed at:** `5acdeb9` (Codex: `dee8e92` evidence bundle + `5acdeb9` hidden-field hardening).
**Suite:** `pytest -q` → **407 passed, 1 skipped, 5 xfailed, 0 failed**.
`real_submission_enabled` stays `false`.

---

## What Codex delivered (`dee8e92`)
- `scripts/live_dry_run.py` — reproducible: `--url`, real Playwright, `--real-submission-enabled` →
  `SystemExit`; acquires a worker lease; optional `--approved-by` gate before autofill via
  `ApprovedAutofillPreviewBuilder`.
- 4 archived bundles under `artifacts/phase43-anthropic-4461450008{,-v2,-v3,-v4}/`, each with
  `report.json`, `dom.sanitized.html`, `field_map.json`, `browser_actions.jsonl`, `safety.json`,
  `transcript.sanitized.json`, `before_fill.png`, `after_fill.png`, `run.sqlite3`.
- `tests/test_live_evidence_bundle.py`.

## Independent verification (reviewer)
- **DOM is a genuine live Greenhouse capture.** `dom.sanitized.html` (105 KB) contains real Anthropic
  font assets (`AnthropicSansDisplay-Semibold-Static.otf`), the real `anthropic.com/candidate-ai-guidance`
  AI-policy link, the embedded Greenhouse form-descriptor JSON, and role-specific question text. Matches
  the reviewer's own read-only navigation (Round 3.3): HTTP 200, title "Job Application for Account
  Executive, AI Native at Anthropic".
- **Field map is DOM-traceable.** All 24 `field_map.json` entries trace by label or selector id into
  `dom.sanitized.html` (`tests/test_round34_evidence_audit.py::test_every_field_map_entry_traces_to_the_captured_dom`).
  The custom questions carry real Greenhouse `question_########` ids; the sponsorship question is present
  and `required: true`; the arbitration-agreement fields resolve `HUMAN_REQUIRED` (correct).
- **Action log** is ordered, time-sorted, `lease_epoch`-stamped, and contains only
  NAVIGATE / SCAN_HARD_STOP / EXTRACT_FIELDS / POST_FILL_SCAN — no submit token.
- **`safety.json`**: `submit_invocation_count 0`, `mismatch_count 0`, `unplanned_browser_actions 0`.
- **PII:** `run.sqlite3` and the transcript contain no candidate data — but only because
  `config/candidate_profile.yaml` is 20× `TODO`.

## P2-21 — hidden/honeypot exclusion — **FIXED** (`5acdeb9`)
`_is_noninteractive` now excludes `hidden` attr, `disabled`, `aria-hidden="true"`, `display:none`,
`visibility:hidden`, `opacity:0`, `tabindex="-1"`+hidden/offscreen class, and `position:absolute` with
`left/top:-9xxx`. `tests/test_round32_regressions.py::test_other_hidden_field_techniques_are_also_excluded`
now passes. (P3: a legitimately `disabled` **required** field is now silently dropped rather than flagged
unresolved — low risk, worth a note.)

---

## Gate G scorecard

| Requirement | Verdict |
|---|---|
| real navigation | **PASS** (reviewer-confirmed + script) |
| real DOM capture | **PASS** (105 KB, corroborated) |
| traceable field map | **PASS** (24/24 trace to DOM; real question ids) |
| safe hidden-field exclusion | **PASS** (`5acdeb9`) |
| lease-fenced autofill | **FAIL** — see P1-28 below |
| approved transcript | **PARTIAL** — the *script* enforces it (`--approved-by` → `ApprovedAutofillPreviewBuilder.build()`); the reusable `GreenhouseLiveDryRunRunner` does **not**; and the archived run was capture-only, so the approved-autofill path was never exercised on the live page |
| action log | **PASS** |
| post-fill safety check | **PARTIAL** — `POST_FILL_SCAN` logged, but no fill occurred so nothing was scanned |
| transcript/browser diff = 0 | **NOT EXERCISED** — `attempted_field_count: 0` (capture-only) |
| submit risk absent | **PASS** (count 0; no submit primitive; script `SystemExit` on real submission) |
| artifact bundle complete | **PARTIAL** — all files present, but see P2-24/25/26 |
| PII-safe evidence | **PARTIAL** — clean today only because the profile is `TODO`; `transcript.sanitized.json` and `run.sqlite3` have no real sanitization and will leak once the real profile is used |

## **Gate G — FAIL (near miss).** Real navigation + traceable DOM + reproducible script are in place.
Remaining blockers: P1-28, and a live *approved-autofill* run with a real before/after form screenshot
and an exercised transcript↔browser differential.

---

## Findings

### P1-28 — lease fencing not enforced; approval gate only in the script, not the runner. **(open)**
**Files:** `scripts/live_dry_run.py`, `app/applications/greenhouse_live.py`.
- The script claims a lease and stamps `lease_epoch` on every action, but **never calls
  `lease_still_mine()`** — not before nav, capture, autofill, or screenshot. If `--approved-by` is
  supplied and the lease expires mid-run, `DryRunBrowserAutofill().apply()` still fills every field. The
  `lease_epoch` in the log is decorative.
- `GreenhouseLiveDryRunRunner` (the reusable class) has **no** `lease_still_mine` and **no**
  `ApprovedAutofillPreviewBuilder` — `human_invoked=True` is its only guard.
**Fix:** in both paths, `assert repo.lease_still_mine(app_id, worker_id, epoch)` before every browser
mutation (nav, each fill batch, upload, screenshot, persistence); abort with no side effects on failure.
Route live autofill through `ApprovedAutofillPreviewBuilder.build()` (validates approval freshness +
`payload_hash` + resume hash + `would_submit`) in the runner too, not just the script.
**Test:** `tests/test_round34_evidence_audit.py::test_live_runner_enforces_lease_and_approval` (xfail).

### P2-23 — raw `run.sqlite3` committed (×4). **(open)**
`.gitignore` has `*.sqlite3`; the 4 `run.sqlite3` (143 KB each) were force-added. PII-clean now (profile
TODO), but once the real profile is used the DB holds resolved candidate values in
`dry_run_transcripts.payload_json` / `applications`. **Fix:** `.gitignore` `artifacts/**/run.sqlite3`
(or use an in-memory DB for evidence runs); keep only `transcript.sanitized.json`.
**Test:** `::test_run_sqlite3_is_not_committed` (xfail).

### P2-24 — before/after screenshots are the JD fold, not the form region. **(open)**
`page.screenshot()` with no `full_page=True` / no scroll to `#application_form` → 1280×720 top of page
= job description. `before_fill.png` is byte-identical to the original `greenhouse_anthropic_4461450008.png`;
`after_fill.png` shows the same JD fold. And no fill occurred, so there is no meaningful before/after.
**Fix:** `full_page=True`, or `page.locator("#application_form").screenshot(...)` before and after fill.
**Test:** `::test_screenshots_show_the_application_form_region` (xfail).

### P2-25 — `transcript.sanitized.json` is not sanitized. **(open)**
`scripts/live_dry_run.py:103` writes `json.dumps(transcript.payload)` verbatim under a "sanitized"
filename — no redaction pass, no `sanitized: true` marker. Harmless today (payload has no resolved
values because the profile is TODO); a real-profile run would write candidate PII to a file named
"sanitized". **Fix:** run the same email/redaction pass (and a proper one — see P2-26) over the payload;
add a `sanitized` marker; redact any `resolved_value` for `legal_sensitive` / PII fields.
**Test:** `::test_transcript_sanitized_json_is_actually_sanitized` (xfail).

### P2-26 — `_sanitize_html` over-redacts non-PII and under-redacts structured PII. **(open)**
`r"(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)" → [REDACTED_PHONE]` nukes the Greenhouse **job/requisition id**
(`4461450008`), CDN asset path numbers, and `?cache-buster` query params — degrading DOM auditability
(the job id can no longer be verified in the DOM). It also does nothing for names, street addresses,
session tokens, or cookies embedded in `<script>` / `data-*`. **Fix:** anchor the phone pattern to
phone-shaped separators / `tel:` / `type="tel"` contexts; keep numeric ids in URLs and asset paths;
add targeted redaction for the known candidate-profile field values.
**Test:** `::test_sanitizer_does_not_redact_the_job_requisition_id` (xfail).

### P3
- 4 near-duplicate bundles committed (~1.5 MB); keep one canonical `phase43` bundle. The base bundle is
  missing `report.json`.
- The `dom.sanitized.html` capture is React-hydration-timing-dependent — it contains only ~5 native
  `<input>` + 1 `<textarea>` (vs ~29 inputs in a fully-hydrated capture); field extraction leans on the
  embedded Greenhouse form-descriptor JSON. Capture should wait for the form (`networkidle` / explicit
  wait) so `dom.sanitized.html` is a stable, complete snapshot.
- `_is_noninteractive` now drops any `disabled` input — a `disabled` **required** field is silently
  dropped rather than surfaced as unresolved.
- `report.hidden_fields_excluded_count` is a re-derived regex count of the raw HTML, not the count the
  extractor actually excluded.

---

## New P0: none.  Open P1: **P1-28** (lease fencing + runner-side approval gate).

## May Codex proceed to Lever / Ashby?
**Not yet.** Close P1-28 and produce one *approved-autofill* Greenhouse live run with (a) `lease_still_mine`
checks logged around each mutation, (b) a real form-region before/after screenshot, (c) an exercised
transcript↔browser differential (`attempted_field_count > 0`, `mismatch_count 0`), (d) a genuinely
sanitized transcript, (e) `run.sqlite3` un-committed. Then Gate G can PASS and Lever review begins.

## Remaining blockers before controlled real submission (unchanged + this round)
1. P1-28 — lease-fence + runner-side approval gate for live autofill.
2. P2-25 / P2-26 — real sanitization of `transcript.sanitized.json` and `dom.sanitized.html` before any
   real-profile run.
3. P2-23 — stop committing `run.sqlite3`.
4. P2-24 — form-region screenshots.
5. A real submit worker still does not exist.
6. `real_submission_enabled` stays `false` until ≥3 fully-audited *approved-autofill* dry-run bundles per
   ATS (Greenhouse, Lever, Ashby).

## Codex autonomous follow-up

Verification: `pytest -q` -> **412 passed, 1 skipped**.

- P1-28: the reusable live runner accepts worker fencing metadata and an approved transcript identifier;
  it checks ownership before navigation, DOM work, and autofill checkpoints. Autofill remains impossible
  without explicit human invocation and approval.
- P2-21: hidden, disabled, opacity-zero, and clearly offscreen controls are excluded and covered by
  promoted regression tests.
- P2-23: evidence-run SQLite files are ignored and removed from committed bundles.
- P2-24: evidence script captures the application form region when available, otherwise a full-page image.
- P2-25/P2-26: transcript payloads are marked sanitized with sensitive values redacted; HTML phone
  redaction is separator/context constrained so requisition IDs remain auditable.

Gate G remains conditional on a real candidate profile and a reviewer-approved, `would_submit=true`
transcript before any live autofill. The current TODO-backed profile intentionally produces
`HUMAN_REQUIRED`; no synthetic data crosses into real submission.
