# DRY_RUN_DESIGN.md — Application Dry-Run Transcript

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Purpose:** before any submission, produce a complete, inspectable record of **exactly what the agent
would submit** — every field, its value, its source, its confidence — plus everything it cannot answer.
The dry-run is the gate a human uses to trust the pipeline before `real_submission_enabled` is ever
flipped.

---

## 1. Where the dry-run sits

```
job -> persona -> resume artifact (validated) -> form engine resolves every field
                                                        │
                                                        ▼
                                              DRY-RUN TRANSCRIPT  ◄── persisted, immutable
                                                        │
                                        ┌───────────────┴───────────────┐
                          any BLOCKED / HUMAN_REQUIRED            all FILLED, human approved
                                        │                               │
                                 application -> HUMAN_REQUIRED    (only if real_submission_enabled
                                 + human_task per unresolved       AND job allowlisted AND approval)
                                                                        │
                                                                  controlled submit
```

The transcript is produced on **every** application attempt, whether or not submission is enabled. With
`real_submission_enabled: false` (always, for now) the pipeline stops at the transcript and opens human
tasks for anything unresolved.

---

## 2. Transcript content

```jsonc
{
  "transcript_id": "dry_<uuid>",
  "application_id": "<uuid>",
  "created_at": "2026-09-07T18:22:00Z",
  "generator_version": "form-engine@<hash>",
  "real_submission_enabled": false,

  "job": { "company": "Example Corp", "role": "Product Analyst", "ats": "greenhouse",
           "job_id": 123, "requisition_key": "R-2026-0912", "apply_url": "https://…",
           "job_content_hash": "…", "revalidated_open": true },

  "persona": "PRODUCT_PM",
  "resume": { "resume_id": "resume_abc123", "file": "resume_abc123.pdf",
              "file_hash": "sha256:…", "truth_validation": "PASS",
              "cited_fact_ids": ["edu.primary.school", "skill.sql", "project.retail_dashboard.1"] },

  "fields": [
    { "label": "First Name", "canonical_key": "personal.first_name",
      "value": "Jane", "policy": "PROFILE_REQUIRED", "source": {"fact_id": "name.full"},
      "confidence": "PROFILE", "required_by_form": true, "status": "FILLED" },
    { "label": "Email", "canonical_key": "personal.email", "value": "jane@…",
      "policy": "PROFILE_REQUIRED", "source": {"fact_id": "contact.email"},
      "confidence": "PROFILE", "required_by_form": true, "status": "FILLED" },
    { "label": "Are you legally authorized to work in the US?",
      "canonical_key": "work_auth.authorized_us", "value": "Yes",
      "policy": "NEVER_GUESS", "source": {"answer_key": "work_authorized_us", "approved_by": "human"},
      "confidence": "AUTO_FROM_PROFILE", "legal_sensitive": true, "required_by_form": true,
      "status": "FILLED" },
    { "label": "Will you now or in the future require sponsorship?",
      "canonical_key": "work_auth.future_sponsorship", "value": "Yes",
      "policy": "NEVER_GUESS", "source": {"answer_key": "requires_sponsorship_now_or_future"},
      "legal_sensitive": true, "status": "FILLED" },
    { "label": "Desired salary", "canonical_key": "compensation.salary_expectation",
      "value": null, "policy": "PROFILE_REQUIRED", "source": {"fact_id": "comp.target_base"},
      "required_by_form": true, "status": "BLOCKED", "reason": "PROFILE_INCOMPLETE" }
  ],

  "custom_questions": [
    { "n": 1, "question": "Why do you want to work at Example Corp?",
      "kind": "long_text", "answer": null, "status": "HUMAN_REQUIRED",
      "reason": "ESSAY_QUESTION" },
    { "n": 2, "question": "Are you comfortable with SQL? (Yes/No)", "kind": "bool",
      "answer": "Yes", "status": "FILLED", "policy": "PROFILE_REQUIRED",
      "source": {"fact_id": "skill.sql"}, "confidence": "PROFILE" }
  ],

  "unresolved": [
    { "kind": "field",   "ref": "compensation.salary_expectation", "reason": "PROFILE_INCOMPLETE",
      "human_task_id": "task_1" },
    { "kind": "question", "ref": "custom_questions[1]", "reason": "ESSAY_QUESTION",
      "human_task_id": "task_2" }
  ],

  "would_submit": false,               // true only if unresolved==[] AND all required FILLED
  "blocking_reasons": ["PROFILE_INCOMPLETE", "ESSAY_QUESTION"],
  "screenshots": ["artifacts/dry_<uuid>/form_top.png", "…"],
  "dom_snapshot": "artifacts/dry_<uuid>/form.html"
}
```

Rules:
- `would_submit` is computed, never set by an adapter. `unresolved != []` ⇒ `would_submit=false`.
- Every `FILLED` row **must** carry a `source` (`fact_id` or `answer_key`) or a `constant` marker.
  A FILLED row with no source is a bug ⇒ transcript build fails.
- `legal_sensitive` rows always show the `answer_key` and whether a human approved that canonical answer.
- Values are the literal strings that would be typed/selected (post option-mapping).

---

## 3. Persistence

```sql
CREATE TABLE IF NOT EXISTS dry_run_transcripts (
    transcript_id   TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL,
    job_id          INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    would_submit    INTEGER NOT NULL,
    blocking_json   TEXT NOT NULL DEFAULT '[]',
    payload_json    TEXT NOT NULL,          -- the full document above
    payload_hash    TEXT NOT NULL,          -- sha256 of payload_json, for change detection
    approved_by     TEXT,                   -- human sign-off (nullable)
    approved_at     TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(application_id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_dryrun_app ON dry_run_transcripts(application_id, created_at);
```

- One transcript per attempt; keep history (regeneration after a profile edit produces a new row).
- `payload_json` is immutable once written. Approval is a separate `UPDATE` of `approved_by/at` only.
- Store screenshots + DOM under `artifacts/<transcript_id>/`.

---

## 4. Human-facing rendering

A `render_transcript(transcript_id) -> str` produces the plain-text preview (the format in the task
prompt: APPLICATION PREVIEW / FIELDS / CUSTOM QUESTIONS / UNRESOLVED). Also emit a one-line summary for
the daily report: `company | role | ats | fields_filled/total | unresolved_count | would_submit`.

`explain_field(transcript_id, canonical_key)` → shows the field, its value, the exact fact/answer text it
came from, and the validator verdict (ties into `RESUME_TRUTH_SYSTEM.md` `explain_resume`).

---

## 5. Gate semantics

| Condition | Result |
|---|---|
| `unresolved != []` | application → `HUMAN_REQUIRED`; one `human_task` per unresolved item; **no submit** |
| `would_submit == true` AND `real_submission_enabled == false` | stop at transcript; log `DRY_RUN_COMPLETE`; leave application in `READY` (or a `DRY_RUN_APPROVED_PENDING` sub-state) |
| `would_submit == true` AND `real_submission_enabled == true` AND job allowlisted AND `approved_by` set | proceed to controlled submit |
| resume `truth_validation != PASS` | application → `HUMAN_REQUIRED` (`TRUTH_VALIDATION_FAILED`); no transcript "would_submit" |

The agent never flips `real_submission_enabled`, never self-approves a transcript, and never submits a
transcript whose `payload_hash` changed after approval.

---

## 6. Tests (add with the feature)

`tests/test_dry_run.py`:
- transcript built for a fully-resolvable application ⇒ `would_submit=true`, every FILLED row has a source
- one missing required fact ⇒ `would_submit=false`, `blocking_reasons=["PROFILE_INCOMPLETE"]`, a task opened
- an essay custom question ⇒ `HUMAN_REQUIRED`, task opened, not submitted
- a legal question auto-answered only when `answer_key` present + approved; otherwise `HUMAN_REQUIRED`
- `real_submission_enabled=false` ⇒ pipeline never calls `adapter.submit()` even when `would_submit=true`
- transcript `payload_json` is immutable; re-generation creates a new row
- approval + later payload change ⇒ submit refused
