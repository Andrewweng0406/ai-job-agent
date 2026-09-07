# SUBMISSION_VERIFICATION.md — Verification Strategy

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Rule:** an application counts toward the daily target **only** when it reaches `VERIFIED`, and
`VERIFIED` requires concrete evidence. A clicked submit button is not evidence.

---

## 1. Confidence levels

| Level | Meaning | Counts toward target? | Retryable? |
|---|---|---|---|
| `VERIFIED` | Concrete evidence the ATS accepted the application (see §2). | **Yes** | No (terminal) |
| `SUBMITTED` (transient) | Submit POST returned a success-shaped response / success page, but evidence not yet captured/matched. Awaiting the verify worker. | No | No — only the verify worker acts on it |
| `SUBMISSION_UNKNOWN` | Submit was attempted; outcome indeterminate (timeout after POST, ambiguous page, no evidence within window). | **No** | **No** — never auto-resubmit; human-resolve only |
| `FAILED` | Explicit, pre-submission failure with no server-side application created (validation error before submit, adapter error before the POST, network error before the POST). | No | Yes, if `attempt_count < cap` and the failure is transient |

`SUBMITTED` is an internal waypoint, not a reportable success. Only `VERIFIED` is.

---

## 2. Acceptable evidence (any ONE promotes `SUBMITTED`/`SUBMISSION_UNKNOWN` → `VERIFIED`)

| Tier | Evidence | How captured | Strength |
|---|---|---|---|
| **T1 — Confirmation ID** | A requisition/confirmation/application number shown on the post-submit page or returned by the submit API. | Regex/DOM scrape of the success page; parse of the submit XHR/GraphQL response. Store verbatim in `confirmation_data_json.confirmation_id`. | Strongest |
| **T2 — Explicit backend success** | Submit endpoint returns an application/candidate id or `status: "submitted"/"received"` in a structured body (Ashby GraphQL, Greenhouse-hosted POST, Workday CXS submit). | Inspect the network response of the submit call. Store `confirmation_data_json.backend_ref`. | Strong |
| **T3 — Confirmation email** | Email arrives at the candidate mailbox from the ATS/employer domain, matching company + role + a time window (submit_time ± 45 min). | IMAP poll by the verify worker; match on sender domain, subject/body keywords, and job title tokens. Store `confirmation_data_json.email_message_id`. | Strong (async) |
| **T4 — Authenticated portal entry** | Reloading the ATS account's "My Applications"/"Candidate Home" shows this requisition as submitted. | Adapter re-auths and asserts the req id is present with a submitted status. Store `confirmation_data_json.portal_seen_at`. | Strong (account ATS only) |
| **T5 — Confirmation page text (weak)** | Success page with unambiguous language ("Your application has been submitted", "Thank you for applying") but **no** capturable id. | DOM text match against an allowlist of confirmation phrases + screenshot stored. | Weak — acceptable **only** if combined with T3 within the window; alone → stays `SUBMITTED`, then `SUBMISSION_UNKNOWN` at window end |

**Not acceptable as evidence:** the submit button became disabled; a spinner appeared; the URL changed;
`HTTP 200` with an unparsed HTML body; absence of an error message; a screenshot with no matched text.

---

## 3. Verify worker (async, separate from the apply worker)

```
on application entering SUBMITTED or SUBMISSION_UNKNOWN:
    record submit_time, evidence collected so far
    verification_window = 45 min (configurable per ATS)
    loop until VERIFIED or window elapsed:
        - if success page had T1/T2 evidence already -> VERIFIED (immediate)
        - poll candidate mailbox for T3 match
        - for account ATSes: after >=10 min, re-auth and check T4
        - backoff between polls (e.g. 2,5,10,15 min)
    window elapsed with no tier met:
        SUBMITTED           -> SUBMISSION_UNKNOWN
        SUBMISSION_UNKNOWN   -> open human_task(category=SUBMISSION_UNKNOWN) while keeping application in SUBMISSION_UNKNOWN
```

- The apply worker never blocks on verification; it hands off and moves to the next application.
- `SUBMITTED → VERIFIED` and `SUBMISSION_UNKNOWN → VERIFIED` must both be legal state transitions
  (currently `SUBMISSION_UNKNOWN → VERIFIED` is **not** — see `CLAUDE_REVIEW.md` P0-6 / P1-8).
- A later rejection/withdrawal email does **not** decrement the `VERIFIED` count; annotate only.

---

## 4. Retry rules (duplicate-application prevention)

| Situation | Action |
|---|---|
| `FAILED` before any submit POST, transient (network/5xx/rate-limit), `attempt_count < 3` | `FAILED → RETRY_PENDING → APPLYING`, backoff + jitter. Same `dedupe_key`, same application row. |
| `FAILED` before submit, non-transient (form mapping, unsupported field) | `→ HUMAN_REQUIRED`. No blind retry. |
| `SUBMISSION_UNKNOWN` (any cause) | **No automated retry, ever.** Verify worker → if evidence found, `→ VERIFIED`. Else → `human_task` while the application remains `SUBMISSION_UNKNOWN`. Human resolves to `VERIFIED` (they confirmed in the ATS) or `SKIPPED`. |
| Submit POST fired then process crashed | On recovery, the `applications` row is in `APPLYING` or `SUBMISSION_UNKNOWN` (written **before** the POST per P0-2). Recovery routes it to the verify worker, never re-drives the form. |
| ATS shows "you have already applied" | Treat as evidence of a prior submission: if a prior `VERIFIED`/`SUBMITTED` row exists → close as `VERIFIED`; else `→ SKIPPED` (`DUPLICATE`). Never submit again. |
| `attempt_count` hits cap (3) in any transient loop | `→ HUMAN_REQUIRED`. |

Global guards:
- `dedupe_key = sha256(candidate_id | canonical_company_id | requisition_key)` is `UNIQUE` on
  `applications`; the row is created **before** the form is opened.
- Every retry reuses that row; a retry never inserts a new application.
- Per-company cooldown after a `CAPTCHA`/block so retries don't hammer and trip anti-bot.

---

## 5. Evidence storage

`applications.confirmation_data_json` schema:
```json
{
  "tier": "T1|T2|T3|T4|T5",
  "confirmation_id": "R-123456",
  "backend_ref": "app_abc123",
  "email_message_id": "<...@ats.com>",
  "portal_seen_at": "2026-09-06T21:14:00Z",
  "success_page_screenshot": "artifacts/app_<id>/success.png",
  "success_page_text_match": "Your application has been submitted",
  "submit_time": "2026-09-06T20:41:00Z",
  "verified_at": "2026-09-06T20:52:00Z"
}
```
Keep the screenshot + DOM snapshot for every `SUBMITTED`, `VERIFIED`, and `SUBMISSION_UNKNOWN` — they are
the audit trail and the input to human resolution.

Implementation note: `app/tracking/verification.py` persists evidence into
`applications.confirmation_data_json`. Only T1-T4 evidence promotes an application to `VERIFIED`; T5 is
stored for audit but remains unverified until stronger evidence arrives.

---

## 6. Reporting

Daily report must show, per ATS and total: `apply_attempts`, `submitted`, `verified` (KPI),
`submission_unknown`, `failed`, plus verify-tier distribution and median `submit_time → verified_at`.
Health rule: mature adapter with `submission_unknown / apply_attempts > 15%` → freeze and investigate.
