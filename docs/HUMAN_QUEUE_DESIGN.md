# HUMAN_QUEUE_DESIGN.md — Human-Required Queue

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Purpose:** define how the system **pauses safely**, **persists everything needed to resume**, and
**resumes without duplicating a submission**, whenever a step needs a human.

---

## 1. When to enqueue a human task (triggers)

| Trigger | Category | Blocking point | Auto-resumable after human? |
|---|---|---|---|
| CAPTCHA / bot challenge | `CAPTCHA` | during `fill`/`submit` | Yes — human solves in the live session, then hands back |
| MFA / OTP / authenticator prompt | `MFA` | account login / submit | Partial — human completes MFA, session token cached briefly |
| Email verification link required | `EMAIL_VERIFICATION` | account creation | Yes — human (or mailbox automation for the candidate's own inbox) clicks link |
| Account creation rejected (dup email, field validation) | `ACCOUNT_CREATION` | pre-apply | Yes after human fixes credentials/alias |
| Ambiguous sponsorship / legal question | `LEGAL_QUESTION` | `answer_questions` | Yes — human supplies the answer, cached as a new canonical `application_answers` entry (with approval) |
| Salary free-text / knockout threshold | `SALARY_FREE_TEXT` | `answer_questions` | Yes — human types value/text |
| Legal certification checkbox ("I certify under penalty of perjury…") | `LEGAL_CERTIFICATION` | pre-submit | Yes — only a human may check it |
| Unexpected essay / long free-text question | `ESSAY_QUESTION` | `answer_questions` | Yes — human writes or approves generated text |
| Dropdown/typeahead with no mappable option | `FORM_MAPPING` | `fill` | Yes |
| Unknown multi-step form / ATS layout changed | `ATS_CHANGED` | any | No — needs an adapter fix first; task is a bug report |
| `verify_submission()` returned no evidence within the window | `SUBMISSION_UNKNOWN` | post-submit | Terminal-ish — human checks the ATS and resolves to VERIFIED or SKIPPED; **system never re-submits** |
| Resume truth-validation failed after regen attempts | `TRUTH_VALIDATION` | pre-apply | Yes — human edits profile facts or approves/rejects the bullet |
| Profile fact required by a field is `TODO`/missing | `PROFILE_INCOMPLETE` | any | Yes — human fills the fact, task auto-closes on next run |

---

## 2. `human_tasks` table (proposed — isolated addition)

```sql
CREATE TABLE IF NOT EXISTS human_tasks (
    task_id           TEXT PRIMARY KEY,              -- uuid4
    application_id    TEXT,                          -- nullable (discovery/profile tasks)
    job_id            INTEGER,
    category          TEXT NOT NULL,                 -- see triggers table
    status            TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN | IN_PROGRESS | RESOLVED | CANCELLED
    blocking_state    TEXT NOT NULL,                 -- ApplicationStatus the app was parked in
    prompt            TEXT NOT NULL,                 -- verbatim question / what the human must do
    options_json      TEXT NOT NULL DEFAULT '[]',    -- choices if it's a select
    context_json      TEXT NOT NULL DEFAULT '{}',    -- URL, step index, adapter, screenshot path, DOM snapshot path
    resume_token      TEXT,                          -- opaque handle the adapter uses to continue
    resolution_json   TEXT,                          -- human's answer / decision
    resolved_by       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    expires_at        TEXT,                          -- stale tasks auto-cancel
    FOREIGN KEY(application_id) REFERENCES applications(application_id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_human_tasks_status ON human_tasks(status, category);
CREATE INDEX IF NOT EXISTS idx_human_tasks_app ON human_tasks(application_id);
```

One **open** task per `(application_id, category)` — enforce with a partial unique index or an
application-level guard, so retries don't spawn duplicate tasks.

---

## 3. Pause protocol (adapter side)

When an adapter hits a trigger:

1. **Stop before the irreversible action.** Never click submit / never check a certification box.
2. **Persist state:**
   - transition the application to `HUMAN_REQUIRED` (from `APPLYING`, `READY`, `TAILORING`, etc. — all
     allowed by the state machine) via `transition_application` (atomic, logged).
   - write `applications.human_required_reason = <category>`.
   - capture `context_json`: current URL, step index, adapter name, a screenshot path, a DOM snapshot
     path, and the list of fields already filled (so the human/session can verify nothing was lost).
   - if a live browser session is required to finish (CAPTCHA/MFA), store a `resume_token` that maps to
     a persisted browser-context handle; set `expires_at` short (e.g. 30–60 min) because sessions rot.
3. **Insert the `human_tasks` row** (idempotent on `(application_id, category)`).
4. **Release the worker.** Do not hold a browser/context blocked waiting for a human.
5. **Emit a structured event** `human_task.opened`.

**Never** partially submit. If the form is multi-page and page 1 was saved by the ATS as a draft, record
that in `context_json` so resume continues from the right page.

---

## 4. Resume protocol

Triggered when a human resolves a task (`status → RESOLVED`, `resolution_json` populated):

1. **Re-validate the world.** Re-fetch the job posting; if it 404s / closed → application → `CLOSED`,
   task → `CANCELLED` with note. Do not proceed on a stale posting.
2. **Check idempotency.** Look up `applications.dedupe_key`; if the application is already
   `SUBMITTED`/`VERIFIED` → close the task, do nothing else. If `SUBMISSION_UNKNOWN` → **do not
   re-drive the form**; the only valid outcomes are human-confirmed `VERIFIED` or `SKIPPED`
   (see `SUBMISSION_VERIFICATION.md`).
3. **Apply the resolution:**
   - `LEGAL_QUESTION` / `SALARY_FREE_TEXT` / `ESSAY_QUESTION` / `FORM_MAPPING`: inject the human's value,
     optionally persist it (with an `approved: true` flag) into `application_answers` so the next
     occurrence is `AUTO_FROM_PROFILE`.
   - `CAPTCHA` / `MFA` / `EMAIL_VERIFICATION`: continue the live session via `resume_token` if not
     expired; if expired → restart the adapter flow from the last ATS-persisted checkpoint (draft page),
     not from scratch, and not past a completed submit.
   - `LEGAL_CERTIFICATION`: only the human's explicit "I have checked it" in a supervised session lets
     the flow proceed to submit.
   - `ACCOUNT_CREATION` / `ATS_CHANGED`: re-enter the queue at `QUEUED`/`READY` after the human fixes
     creds / after an adapter patch ships.
4. **Transition** `HUMAN_REQUIRED → READY` (or `→ QUEUED`), then let the normal workflow runner pick it
   up. Increment `attempt_count`. Respect the retry cap (`SUBMISSION_VERIFICATION.md` §4).
5. **Emit** `human_task.resolved` + the subsequent workflow events.

---

## 5. Safety invariants

- A task in `SUBMISSION_UNKNOWN` category **never** results in an automated re-submit. Human resolves it
  to `VERIFIED` (they saw the confirmation in the ATS) or `SKIPPED` (they'll do it manually / it's a
  dup). Enforce by **removing** the `SUBMISSION_UNKNOWN → FAILED → RETRY_PENDING → APPLYING` path
  (see `CLAUDE_REVIEW.md` P0-6).
- Resolving a task requires the application's current status to still be `HUMAN_REQUIRED` (compare-and-set);
  otherwise the resolution is rejected (something else moved it).
- `resume_token` / browser-context handles are secrets → encrypted at rest, short TTL, never logged.
- Human answers to `NEVER_GUESS` topics are cached only with an explicit approval flag and are
  candidate-scoped; they are never shared across candidates (there is only one candidate now, but the
  schema should not assume it).
- Every task carries enough `context_json` for a human to independently verify in the ATS what state the
  application is really in.

---

## 6. Metrics (feed the daily report)

`human_tasks_opened` / `_resolved` / `_cancelled` by category, median age, open backlog, and
`resume_success_rate` (resolved tasks that then reached `VERIFIED` without a new task). A rising
`SUBMISSION_UNKNOWN` or `ATS_CHANGED` backlog freezes the relevant adapter.
