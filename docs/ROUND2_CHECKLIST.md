# ROUND2_CHECKLIST.md — Round 2 Review Plan

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Run this when Codex signals the next milestone** (first working end-to-end discovery→queue→resume, or
the first real ATS `apply()` path). Ordered by blocking severity.

---

## 0. Pre-flight (2 min)

- [ ] `git log --oneline` since `525ecae`; note new modules.
- [ ] `python -m pytest -q` → record pass / xfail / xpass counts. Any **xpass** = a tracked gap Codex
      closed → promote that test to a plain assertion.
- [ ] `grep -rn "TODO\|FIXME\|XXX" app/` and check `config/candidate_profile.yaml` is still all-TODO
      (must be, until the human fills it) and that real submission is still gated.
- [ ] Confirm `config/settings.yaml`: `application_safety.real_submission_enabled: false`.

## 1. Integrity gates (BLOCKING — do first)

- [ ] **P1-13** `ApplicationWorkflowRunner.run()` persists every step via `repository.transition_application`,
      bumps `attempt_count`, sets `applied_at`, and **refuses** to run unless status ∈ {READY, RETRY_PENDING}.
      Verify with `tests/test_adversarial_workflow.py` (should be plain-pass, not xfail).
- [ ] **P1-15** `validate_with_provenance` does real number entailment (number ∈ cited fact text, with
      `50,000`/`50000`/`~50k` normalization), not blanket rejection. `tests/test_resume_redteam.py`
      `test_legit_cited_number_is_accepted` passes AND the inflation cases still fail.
- [ ] **Profile completeness gate**: with any `required: true` fact = `TODO`, resume generation AND
      `apply()` hard-refuse (not just `real_submission_enabled`). Add a test.
- [ ] Every resume bullet + application answer traces to `fact_id`s; unknown legal/authorization question
      → `HUMAN_REQUIRED` (never auto-answered). Spot-check `app/applications/form_fields.py` classifications
      against `docs/FORM_FIELD_TAXONOMY.md` — all `NEVER_GUESS` fields with no canonical answer → human.
- [ ] `verify_submission()` returns an evidence **tier** (T1–T5 / UNKNOWN per `SUBMISSION_VERIFICATION.md`),
      not a bare bool. Nothing counts as `VERIFIED` without stored evidence in `confirmation_data_json`.
- [ ] State machine: re-run the graph-reachability test — `SUBMISSION_UNKNOWN` cannot reach `APPLYING`/
      `RETRY_PENDING`; `VERIFIED` is the only terminal success; `* → CLOSED` from every pre-submit state.

## 2. Concurrency / data (BLOCKING before `application_concurrency > 1`)

- [ ] **P1-14** discovery insert/transition is CAS (transition only if row still `DISCOVERED`; benign
      race swallowed). `_incremental_status` folded into the upsert (no separate connection).
- [ ] `mark_human_required` is one `BEGIN IMMEDIATE` transaction (transition + reason UPDATE together).
- [ ] Indexes present: `idx_applications_status`, `idx_transitions_app`, `idx_jobs_company_status`,
      `idx_jobs_incremental`, partial unique `human_tasks(application_id, category) WHERE status='OPEN'`.
- [ ] Row-claim pattern (`worker_id`, `claimed_at`) + stuck-row reaper exists; reaper routes
      pre-submit → `RETRY_PENDING`, post-submit-fired → `SUBMISSION_UNKNOWN`.
- [ ] Application `dedupe_key` is requisition-based (`candidate_id | company_id | req_key`) — re-inserting
      the same requisition as a new `jobs` row does NOT create a second application. Add that test.
- [ ] `upsert_job` ON CONFLICT refreshes ALL mutable columns (P2-1): `requirements_json`,
      `preferred_qualifications_json`, `salary_*`, `remote_status`, `employment_type`, `posted_at`,
      `source_url`, `apply_url` — and recomputes `status` from `description_hash` diff.

## 3. Discovery adapters

- [ ] Contract tests green for every implemented adapter (`tests/test_source_contracts.py`): external id,
      canonical + source URL, title, company, location, description, **posted_at populated**, apply URL.
- [ ] New adapters (SmartRecruiters / Workday / …): promote the xfail contract tests; fixtures already in
      `tests/fixtures/ats/`. Workday external id = `jobRequisitionId` (not `externalPath`).
- [ ] All outbound HTTP goes through one shared client with **per-host + per-ATS rate limits**, honors
      `Retry-After`, jittered backoff. `JsonHttpClient` today has none — check for a limiter.
- [ ] Incremental crawl: unchanged posting (same `content_hash`) → no re-filter, no LLM. `JobStatus`
      `UPDATED`/`UNCHANGED` actually computed and acted on.
- [ ] Non-US / stale postings filtered (P2-8 normalizer); `location_unknown` kept per PRIMARY PRINCIPLE.

## 4. Filters (adversarial regression — should all be green)

- [ ] `tests/test_adversarial_filters*.py`, `test_adversarial_dedup*.py` all pass.
- [ ] Sponsorship pattern refactored to compositional rule (P1-16) — spot-check 3 novel phrasings not in
      the test file.
- [ ] Family classification: `UNKNOWN` title → kept and routed to LLM stage, never dropped (P2-5).
- [ ] Experience: `0-2`, `1-3`, `1–5`, `3 to 5`, `up to 4` kept; `min 5`, `7+`, `8 years` skipped;
      years in a "Preferred" block ignored.

## 5. Failure handling

- [ ] Each `FailureCategory` in `docs/FAILURE_MODEL.md` §2 has a code path + a test (at least the A/E/F
      rows). `SUBMISSION_UNKNOWN`, `EXPORT_CONTROL_RESTRICTED`, `PROFILE_INCOMPLETE`,
      `TRUTH_VALIDATION_FAILED` present.
- [ ] CAPTCHA / MFA / unknown-legal-question paths in `apply()` → `HUMAN_REQUIRED` + snapshot, tested,
      no solver/evasion anywhere in the tree (`grep -rn "captcha\|2captcha\|anticaptcha" app/`).
- [ ] `human_tasks` pause/resume protocol (`docs/HUMAN_QUEUE_DESIGN.md`): resume re-validates the posting,
      checks idempotency, never re-drives a completed submit.

## 6. Cost (cross-ref `docs/LLM_COST_STRATEGY.md`)

- [ ] No LLM call before deterministic filters. Stage-1 extraction batched + `content_hash`-cached.
      Strong model gated. Resume artifact cache keyed `(persona, skills, schema_version)`.
- [ ] Per-stage LLM call + $ counters in the daily report.

## 7. Observability

- [ ] Daily report shows: discovered / deduped / filtered-by-reason / eligible / queued / attempts /
      submitted / **verified** / submission_unknown / failed / human tasks, per-ATS.
- [ ] Structured events (not logs) for each stage transition; no PII / secrets in events or prompts.

## 8. Throughput sanity

- [ ] Re-run `docs/THROUGHPUT_MODEL.md` numbers with any measured rates now available.
- [ ] `application_concurrency` still 1 unless §1 + §2 are all checked; then bump to 3–4 and re-measure.

---

## Exit criteria for Round 2 sign-off

1. §1 fully checked (integrity gates) — **hard blocker**, no exceptions.
2. §2 checked OR `application_concurrency` stays at 1 with a written note.
3. All adversarial/contract suites green; every xpass promoted.
4. New P0/P1 findings appended to `CLAUDE_REVIEW.md` with exact patches.
5. `real_submission_enabled` remains `false` until a human has filled the profile and signed off on a
   dry-run transcript for at least one Greenhouse + one Lever + one Ashby application.
