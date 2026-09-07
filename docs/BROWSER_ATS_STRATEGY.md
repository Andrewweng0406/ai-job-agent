# BROWSER_ATS_STRATEGY.md — Greenhouse / Lever / Ashby Browser Application Strategy

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Status:** Phase 4 implementation guidance. `real_submission_enabled` stays `false`; first runs are
**dry-run only** (`DRY_RUN_DESIGN.md`). No CAPTCHA/MFA/anti-bot bypass — those are `HUMAN_REQUIRED`.

Scope: the three no-account hosted-apply ATSes are the first real targets (`ATS_MATRIX.md` P1). This doc
covers, per ATS, the 12 steps from job page to verified result. Selectors below are **starting points to
verify against live DOM**, expressed as role/label locators wherever possible.

---

## 0. Common engine (shared by all three)

| Concern | Approach |
|---|---|
| Browser | Playwright, one **fresh context per application** (clean cookies/storage), `en-US`, US egress, realistic viewport. |
| Pacing | Per-domain token bucket (`WORKER_CONCURRENCY.md`): ≤1 concurrent submit per company, jittered 2–6 s between actions, honor any `Retry-After`. |
| Timeouts | Per-application hard cap 6 min; per-action 30 s. On cap with a submit already fired ⇒ `SUBMISSION_UNKNOWN` (never retry). |
| Snapshots | Screenshot + DOM dump + console log on: every failure, every `HUMAN_REQUIRED`, every `SUBMISSION_UNKNOWN`, and the final success page. |
| Field fill | Via the form engine (`APPLICATION_FORM_ENGINE.md`): classify → resolve → set → **re-read & diff**. |
| CAPTCHA / bot wall | `is_captcha_present()` → `HUMAN_REQUIRED` (`CAPTCHA`), snapshot, per-company cooldown. Never solve. |
| Dry-run | Build the full transcript through step 8; **stop before step 9** unless `real_submission_enabled` AND the specific job is on an allowlist AND a human approved the transcript. |

---

## 1. Greenhouse (`job-boards.greenhouse.io` / `boards.greenhouse.io` / embedded iframe)

| Step | Strategy |
|---|---|
| 1. Job page id | Canonical apply URL from discovery (`boards.greenhouse.io/{token}/jobs/{id}`). Also handle the embed: `#grnhse_iframe` — switch into the iframe frame. |
| 2. Form id | `<form id="application_form">` / `<form action*="/applications">`. In embed, inside the iframe. |
| 3. Field discovery | Inputs under `#application_form`. Labels: `label[for]` → input id. Custom questions live in `.field` blocks with `label` + input/select/textarea. Greenhouse question ids look like `job_application[answers_attributes][N][text_value]`. |
| 4. Resume upload | `input[type=file]#resume_or_cv` (or `#s3_upload_for_resume`). After upload, Greenhouse shows a parsed filename + sometimes auto-fills name/email — **diff parsed values vs profile, correct**. Accept `application/pdf`. |
| 5. Dynamic fields | "Add another" for education/employment repeaters; conditional questions appear on select-change. Re-enumerate after every select change. |
| 6. Required detection | `aria-required="true"`, `.field.required`, trailing `*` in label, or a `required` attribute. Also probe: attempt submit on a scratch pass in dry-run to collect the server's required list (dry-run only, never actually posts). |
| 7. Validation errors | After a blocked submit: `#error_explanation`, `.field_with_errors`, per-field `.message` text. Map to `VALIDATION_ERROR`; if pre-submit ⇒ fix or `FORM_MAPPING`→HUMAN_REQUIRED. |
| 8. Custom questions | Enumerate `.field` with a `label` not in the known map → classify via form engine. Legal/authorization phrasing → `NEVER_GUESS`. Unmapped select option → HUMAN_REQUIRED. |
| 9. Submit | `#submit_app` / `button[type=submit]:has-text("Submit Application")`. Record `submit_time` **before** click. |
| 10. Confirmation | Redirect to `.../confirmation` or in-page `#application-confirmation` / text "Your application has been submitted" / "Thank you for applying to". |
| 11. Evidence | T1: Greenhouse rarely shows a numeric confirmation id on the page — capture any `confirmation`/`reference` text if present. T2: inspect the POST `/applications` response (JSON with `success:true`/redirect 302). T3: confirmation email to candidate mailbox (verify worker). Default realistic tier = **T2 + T5**, promoted by **T3**. |
| 12. Failure recovery | Network error before click ⇒ `NETWORK` → `RETRY_PENDING` (cap 3). Error after click ⇒ `SUBMISSION_UNKNOWN`. hCaptcha (some high-volume boards) ⇒ `HUMAN_REQUIRED`. |

Notes: Greenhouse "hosted" vs "embedded" differ only by the iframe hop. EEO block (`#demographic_questions`)
→ all `NEVER_GUESS` defaults (decline).

---

## 2. Lever (`jobs.lever.co/{company}/{id}` → `/apply`)

| Step | Strategy |
|---|---|
| 1. Job page id | `jobs.lever.co/{company}/{uuid}`; apply page `.../apply`. |
| 2. Form id | `form[action*="/apply"]` / `.application-form`. |
| 3. Field discovery | `.application-field` blocks; `input[name="name"]`, `input[name="email"]`, `input[name="phone"]`, `input[name="org"]`, `input[name="urls[LinkedIn]"]`, `input[name="urls[GitHub]"]`. Custom cards: `.application-question` with `.application-label` + input; names like `cards[UUID][field0]`. |
| 4. Resume upload | `input[type=file][name="resume"]`. Lever parses and shows `.resume-upload-success` with extracted fields it may prefill — diff & correct. |
| 5. Dynamic fields | Custom question groups; some `select` reveal follow-ups. Re-enumerate after change. |
| 6. Required detection | `aria-required`, `.application-field.required`, label `*`. Lever marks required questions with `required` on the input. |
| 7. Validation errors | `.form-error` / `.application-field.error .error-message`. Post-submit banner `.postings-btn-wrapper .error`. |
| 8. Custom questions | `.application-question` label text → classify. Lever "Additional information" is a free `textarea[name="comments"]` → `OPTIONAL_SKIP` unless required. |
| 9. Submit | `button.template-btn-submit` / `button:has-text("Submit application")`. `submit_time` before click. |
| 10. Confirmation | Redirect to `.../thanks` or `.../apply/success`; in-page `.application-confirmation` / "Thank you" + role context. |
| 11. Evidence | T2: POST `/apply` returns JSON/redirect. Page `/thanks` URL = T5+. T3 email from `no-reply@hire.lever.co` or the company. No numeric id typically. |
| 12. Failure recovery | Same tiers as Greenhouse. Lever sometimes uses reCAPTCHA v2 on high volume ⇒ `HUMAN_REQUIRED`. |

---

## 3. Ashby (`jobs.ashbyhq.com/{org}/{jobId}` — React SPA)

| Step | Strategy |
|---|---|
| 1. Job page id | `jobs.ashbyhq.com/{org}/{uuid}`; "Apply" opens an in-app form (no separate URL sometimes) — wait for the form container to render. |
| 2. Form id | `form` inside `[class*="ApplicationForm"]`; SPA — wait on network idle + the submit button being present. |
| 3. Field discovery | Field wrappers `[class*="_fieldEntry"]`; labels are `label`/`_label` siblings. Inputs are controlled React components — set value via `fill()` then dispatch `input`/`change`; verify the React state took (re-read). File and select are custom widgets. |
| 4. Resume upload | Custom dropzone `input[type=file]` (often visually hidden) inside `[class*="_resume"]`. Ashby parses; may prefill name/email/links — diff & correct. |
| 5. Dynamic fields | Conditional questions via `showIf`; re-enumerate after every change. Ashby yes/no are custom radio groups. |
| 6. Required detection | `aria-required`, `_required` class, `*` in label. Ashby also disables submit until required set — use the disabled state as a signal. |
| 7. Validation errors | `[class*="_errorText"]` per field; form-level `[role="alert"]`. |
| 8. Custom questions | `[class*="_fieldEntry"]` label → classify. Ashby types: `Yes/No`, `Dropdown`, `Multi-select`, `Free text`, `Long text`, `Number`, `File`. Map kind → form engine. Legal phrasing → `NEVER_GUESS`. |
| 9. Submit | `button[type=submit]:has-text("Submit Application")` (enabled only when valid). `submit_time` before click. |
| 10. Confirmation | SPA swaps to a success view `[class*="_confirmation"]` / "Your application has been submitted"; sometimes shows an application reference. |
| 11. Evidence | **Best of the three.** T1: capture the reference id if shown. T2: the submit GraphQL/REST call returns an application id in the response body — inspect it. T3 email. Ashby → realistic tier **T1/T2** often achievable. |
| 12. Failure recovery | SPA nav failure after submit ⇒ `SUBMISSION_UNKNOWN`; poll the org's public posting for the candidate's state is not possible (no account) → rely on T3 email. |

---

## 4. Evidence tier expectations (feeds `SUBMISSION_VERIFICATION.md`)

| ATS | Realistic on-page tier | Promotable by |
|---|---|---|
| Greenhouse | T5 (thank-you text) + T2 (302/JSON) | T3 email (verify worker, ±45 min) |
| Lever | T5 (`/thanks`) + T2 | T3 email |
| Ashby | **T1/T2** (reference id / API body) | T3 email |

If only T5 at window close ⇒ `SUBMISSION_UNKNOWN` ⇒ `human_task`. Never count T5-alone as `VERIFIED`.

---

## 5. Hard stops (all ⇒ `HUMAN_REQUIRED`, snapshot, no bypass)

- CAPTCHA / hCaptcha / reCAPTCHA / "verify you are human" interstitial
- Any MFA / OTP / SMS / authenticator prompt
- Email-verification-before-submit wall (unless a separately authorized candidate-mailbox workflow exists)
- Login wall / "create an account to continue" (these three ATSes normally don't require it — if one does, stop)
- An unmapped **required** field or an unmappable required select option
- Any legal/authorization free-text question
- DOM shape not matching the adapter's known signatures (`ATS_CHANGED`) — stop that adapter, alert, keep others running

---

## 6. Dry-run acceptance before any real submit is even considered

Per ATS, a human reviews a dry-run transcript (`DRY_RUN_DESIGN.md`) for **≥3 real postings** and confirms:
every FILLED field is correct, every HUMAN_REQUIRED is genuinely judgment, the resume artifact is the
validated one, and no legal field was auto-answered. Only then does the ATS move from "dry-run only" to
"allowlisted for controlled submission", and even then `real_submission_enabled` is flipped by the human,
per-run, not by the agent.
