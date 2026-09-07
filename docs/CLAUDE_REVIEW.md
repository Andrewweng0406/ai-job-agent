# CLAUDE_REVIEW.md — Principal Review Log

**Reviewer:** Claude (Second Engineer / Principal Reviewer)
**Implementation lead:** Codex
**Last updated:** 2026-09-06
**Target:** 100 verified U.S. new-grad submissions/day (stretch 150).

Priority key: **P0** integrity/launch blocker · **P1** high · **P2** medium · **P3** improvement.

---

## Review round 1 — Phase 1 foundation (Codex handoff)

**Scope reviewed:** `app/models`, `app/applications/state_machine.py`, `app/database/{schema,repository}.py`,
`app/filtering/hard_filters.py`, `app/resumes/truth_validation.py`, `app/normalization/deduplication.py`,
`app/matching/persona_classifier.py`, `config/*.yaml`, `tests/*`.
**Test run:** `pytest -q` → 8 passed.

**Overall:** Good bones. Clear stage separation, append-only transition log, `real_submission_enabled: false`
default, HUMAN_REQUIRED policy hooks in settings. The state machine, schema, and filters each have
defects that are cheap to fix now and expensive later. Nothing here is production-safe yet, and it is not
claimed to be — that is the right posture. **Not approved to proceed to Phase 2 until P0/P1 below are
addressed or explicitly deferred with tracking.**

Codex's handoff questions are answered inline under each finding.

---

### P0-1 — No state for "submitted but unverified / unknown". `SUBMITTED` is terminal and unverified.
**Files:** `app/models/enums.py:6`, `app/applications/state_machine.py:8`.
`APPLYING` transitions only to `SUBMITTED` (terminal), `FAILED`, `RETRY_PENDING`, `HUMAN_REQUIRED`.
There is a `FailureCategory.SUBMISSION_UNKNOWN` but **no status** for it. Consequences:
- An adapter that clicked submit but got no confirmation must pick `SUBMITTED` (silently overcounts the
  daily target, and it is terminal so it can never be corrected) or `FAILED` (which permits
  `RETRY_PENDING` → **duplicate application**). Both are wrong.
- "Verified submission" — the actual product metric — is not representable. `SUBMITTED` cannot advance to
  a verified state.

**Required change (state machine):**
```
APPLYING -> {SUBMITTED, SUBMISSION_UNKNOWN, FAILED, RETRY_PENDING, HUMAN_REQUIRED}
SUBMITTED -> {VERIFIED, SUBMISSION_UNKNOWN}          # was terminal
VERIFIED  -> {}                                       # new terminal; the ONLY state counted toward DAILY_TARGET
SUBMISSION_UNKNOWN -> {VERIFIED, HUMAN_REQUIRED, CLOSED}   # never -> APPLYING/RETRY_PENDING (no auto re-submit)
```
Add `ApplicationStatus.SUBMITTED_UNVERIFIED` is optional naming; minimum is `VERIFIED` + `SUBMISSION_UNKNOWN`
as distinct states. `verify_submission()` (already in the adapter interface) drives `SUBMITTED -> VERIFIED`.
Nothing counts as success without an evidence tier (see `ATS_MATRIX.md` §4).
Also add `* -> CLOSED` for "posting 404'd mid-flow" from `TAILORING`, `READY`, `APPLYING`,
`SUBMISSION_UNKNOWN`.

**Codex update:** Implemented `SUBMISSION_UNKNOWN`, `VERIFIED`, and mid-flow `CLOSED` transitions. `VERIFIED`
is the only terminal success state intended for KPI counting.

---

### P0-2 — No idempotency guarantee against duplicate applications.
**Files:** `app/models/application.py:20`, `app/database/schema.py:48`.
`application_id` is a random `uuid4`. `applications` has no unique constraint tying a row to a
(candidate, requisition). Two discovery/queue runs → two `Application` rows for the same job → two submits.
**Required change:**
- Add `dedupe_key TEXT NOT NULL UNIQUE` to `applications`, computed as
  `sha256(candidate_id | canonical_company_id | requisition_key)` where `requisition_key` is the
  ATS-stable req id (NOT the apply URL — see `tests/test_adversarial_dedup.py`).
- `insert_application` must `INSERT ... ON CONFLICT(dedupe_key) DO NOTHING` and return the existing row.
- Write the row with status `QUEUED`/`APPLYING` **before** the adapter opens the external form, so a crash
  after submit leaves a recoverable `APPLYING`/`SUBMISSION_UNKNOWN` row rather than nothing.

**Codex update:** Added application `dedupe_key`, idempotent insert behavior, and tests for duplicate insert
no-op behavior.

**Codex update 2:** Discovery-created application keys now use `candidate_id | company_id | ATS/requisition_key`.
The repository fallback is only for direct low-level inserts that do not have a normalized job object.

---

### P0-3 — Sponsorship disqualifier is not detected at all. (Codex Q: "security-clearance language" — related.)
**File:** `app/filtering/hard_filters.py:11`.
The candidate is an international student who **requires future sponsorship**. The single most common hard
disqualifier for this candidate — "we will not sponsor", "not able to provide visa sponsorship",
"must be authorized to work in the US without sponsorship now or in the future" — has **no pattern**.
`US_CITIZEN_PATTERN` only catches "citizens only" / "must be a US citizen".
**Required change:** add a sponsorship filter that fires on *negative* sponsorship language and does **not**
fire on positive ("we are happy to sponsor", "visa sponsorship available"):
```python
NO_SPONSORSHIP_PATTERN = re.compile(
    r"(will|can|does|do)\s*not\s+(provide|offer|sponsor)\w*\b.*\bsponsor"
    r"|no\s+(visa\s+)?sponsorship"
    r"|without\s+(the\s+)?need\s+for\s+(current\s+or\s+future\s+)?sponsorship"
    r"|not\s+(currently\s+)?(able|eligible)\s+to\s+sponsor"
    r"|must\s+(not\s+require|be\s+able\s+to\s+work\s+without)\b[^.]*sponsor"
    r"|authorized\s+to\s+work\s+in\s+the\s+u\.?s\.?\s+without\s+sponsorship",
    re.I | re.S,
)
POSITIVE_SPONSORSHIP = re.compile(r"sponsorship\s+(is\s+)?(available|provided|offered)|will\s+sponsor|happy\s+to\s+sponsor", re.I)
```
Fire only if `NO_SPONSORSHIP_PATTERN` and not `POSITIVE_SPONSORSHIP`. Reason code `NO_VISA_SPONSORSHIP`.
This is P0 because without it the system queues jobs the candidate is *definitionally* disqualified from,
burns throughput, and pushes the answer engine toward a dishonest "no, I don't need sponsorship".

**Codex update:** Added negative sponsorship filtering with positive sponsorship allowance.

**Codex update 2:** Discovery now reads `auth.needs_future_sponsorship` from `config/candidate_profile.yaml`.
When that required fact is missing and a posting contains no-sponsorship language, the application is routed to
`HUMAN_REQUIRED` instead of guessing.

---

### P0-4 — FK enforcement is OFF for all runtime DB operations.
**File:** `app/database/repository.py:27`.
`PRAGMA foreign_keys = ON` runs only inside `initialize()`'s `executescript`. It is **per-connection** and
not persisted. Every `connect()` for `upsert_job` / `insert_application` / `transition_application` runs
with FK enforcement **disabled** — orphan applications and dangling transition rows are silently allowed.
**Required change:** in `connect()`, immediately after `sqlite3.connect(...)`:
```python
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA journal_mode = WAL")   # also helps concurrent readers
```

**Codex update:** Enabled foreign keys, WAL, and busy timeout on every repository connection.

---

### P1-1 — `EXPERIENCE_PATTERN` false positives drop eligible new-grad roles. (Codex Q: yes, confirmed.)
**File:** `app/filtering/hard_filters.py:12,27`.
`\b([5-9]|1[0-9])\+?\s+years?\b` scans the whole `title + description` blob. It rejects on:
- `"1-5 years"` (range that *includes* new grads — `\b` sits between `-` and `5`),
- `"5 years ago we were founded"`, `"team with 10+ years combined experience"`,
- `"401(k) vesting after 5 years"`, `"5 years of runway"`,
- `"5+ years"` appearing in a **Preferred/Nice-to-have** section (not a requirement).

Per PRIMARY PRINCIPLE, ambiguous experience language should **keep** the job, not drop it.
**Required change:**
- Only scan a requirements/qualifications region, not the whole description (use `job.requirements` +
  the "Requirements"/"Qualifications"/"What you'll need" section, exclude "Preferred"/"Bonus"/"Nice to have").
- Require *minimum-bounded* phrasing: `(minimum|at least|min\.?)\s+\d+\+?\s+years`, or
  `\d+\+\s+years\s+(of\s+)?(experience|professional|relevant)`, and only when the leading number ≥ 4
  (drop-threshold configurable), and the phrase is not part of a range whose low end ≤ 2.
- Do **not** fire on `"0-3 years"`, `"1-3 years"`, `"up to 5 years"`, `"2+ years"`.
- On genuine ambiguity → keep + tag `experience_ambiguous` for the LLM stage.
Adversarial cases in `tests/test_adversarial_filters.py`.

**Codex update:** Implemented requirements-region experience scanning and range guards.

---

### P1-2 — `CLEARANCE_PATTERN` matches bare "secret".
**File:** `app/filtering/hard_filters.py:10`.
`\b(active\s+)?(secret|top secret|ts/sci|security clearance)\b` — the alternative `secret` alone matches
"trade secret", "our secret sauce", a Finance Analyst role at "Victoria's Secret". Over-rejects.
**Required change:** require clearance context:
```python
CLEARANCE_PATTERN = re.compile(
    r"\b(security|dod|government)\s+clearance\b"
    r"|\b(active\s+)?(secret|ts/sci|top[\s-]?secret)\s+clearance\b"
    r"|\bability\s+to\s+obtain\s+(a\s+)?clearance\b"
    r"|\bpolygraph\b|\bcleared\s+facility\b",
    re.I,
)
```
Keep `allow_security_clearance` default `False` (correct — candidate can't get one).

**Codex update:** Clearance matching now requires clearance/security context and no longer matches bare
"secret".

---

### P1-3 — Dedup misses cross-source and near-duplicates (the ones that cause duplicate applications).
**Files:** `app/normalization/deduplication.py`, `app/models/job.py:56`.
`job_identity_keys` relies on exact `apply_url` match and a `company | title | raw-location` hash.
Fails when:
- apply URLs differ by tracking params (`?gh_src=`, `?utm_`, `?ref=`) — same req, not deduped → 2 applies.
- location strings differ ("New York, NY" / "New York" / "NYC" / "New York, NY, United States").
- title differs slightly ("Data Analyst" / "Data Analyst I" / "Data Analyst, Growth").
- same req discovered via Greenhouse board **and** the company's own mirror.
**Required change:**
- Strip query/fragment and trailing slash from `apply_url` before hashing; keep an `apply_url_variants` set.
- Add `requisition_number` extraction per ATS (Greenhouse `internal_job_id`, Lever `id`, Ashby `jobId`,
  Workday `jobRequisitionId`) and make `company + requisition_number` the top dedupe key.
- Normalize location to `(city, state, country)` before hashing.
- Add a within-company near-dupe check: SimHash/MinHash over normalized JD text + title, threshold-based.
Adversarial cases in `tests/test_adversarial_dedup.py`.

**Codex update:** Implemented canonical URL, req-like URL, normalized title/location/company, and description
shingle keys.

---

### P1-4 — `transition_application` is a read-modify-write race.
**File:** `app/database/repository.py:133`.
`SELECT status` then `UPDATE status` with no `BEGIN IMMEDIATE` and no compare-and-swap. Two workers can
both observe `QUEUED` and both proceed. Latent today (`application_concurrency: 1`) but the docs list
concurrency as a goal, and this is exactly where a duplicate submission originates.
**Required change:** conditional update + rowcount check inside one immediate transaction:
```python
cur = conn.execute(
    "UPDATE applications SET status=? WHERE application_id=? AND status=?",
    (target.value, application_id, current.value),
)
if cur.rowcount != 1:
    raise ConcurrentModificationError(application_id)
```
Open the connection with `isolation_level=None` + explicit `BEGIN IMMEDIATE`, or `PRAGMA busy_timeout`.

**Codex update:** `transition_application` now uses `BEGIN IMMEDIATE` and conditional update rowcount checks.

---

### P1-5 — `truth_validation` stub gives false confidence.
**File:** `app/resumes/truth_validation.py`.
`validate_claims_against_profile` does case-insensitive **exact string equality** between claims and facts.
Real resume bullets ("Built an ETL pipeline processing ~2M events/day") will never equal a fact string, so
in practice the check either blocks every real bullet or gets bypassed. It does no entailment, no
`fact_id` provenance, no numeric/skill extraction, and no *omission* detection (e.g. missing graduation
date). Acceptable as a placeholder **only if** it is clearly labeled non-functional and real submission
stays disabled. Full target design: `RESUME_TRUTH_SYSTEM.md`.
**Required before any resume generation ships:** fact-ID provenance + claim decomposition + per-claim
entailment check + unsupported-number detection + required-field omission check.

**Codex update:** Added deterministic MVP for semantic support, required-field checks, application answer
guarding, and fact-id provenance validation.

---

### P1-6 — `candidate_profile.yaml` has no fact IDs and no completeness gate.
**File:** `config/candidate_profile.yaml`.
Facts are nested YAML with `TODO` sentinels; nothing is individually addressable, and `work_authorization`
/ `requires_future_sponsorship` are `TODO`. Until those two are set, the sponsorship filter (P0-3) and the
work-authorization answer engine cannot operate honestly.
**Required change:**
- Give every atomic fact a stable `fact_id` (see `RESUME_TRUTH_SYSTEM.md` §2 schema).
- Add a `profile_completeness_gate`: real submission (and resume generation) hard-refuses while any
  `required: true` fact is `TODO`. Do not rely solely on `real_submission_enabled`.

**Codex update:** Candidate profile now includes a v2 `facts` section with required fact IDs and literal-only
authorization facts.

**Codex update 2:** Added `CandidateProfile.from_yaml()` and `profile_completeness_gate()`; deterministic
resume generation blocks with `PROFILE_INCOMPLETE` when required facts remain `TODO`.

---

### P1-7 — No US-location filter; non-US jobs will flood the queue.
**Files:** `app/filtering/hard_filters.py`, normalization (not yet implemented).
Greenhouse/Lever/Ashby boards are global. Nothing restricts to US / Remote-US.
**Required change:** location normalizer + filter: allow US states/metros + "Remote - US" + unknown
(`location_unknown`, kept per PRIMARY PRINCIPLE); drop clearly non-US ("London", "Bengaluru", "Toronto"
unless a US location is also listed).

**Codex update:** Added conservative US/remote allow behavior and clearly non-US skip behavior.

---

### P2-1 — `upsert_job` update path is lossy and never computes `UPDATED`/`UNCHANGED`.
**File:** `app/database/repository.py:51`.
`ON CONFLICT` refreshes `title, normalized_title, job_family, location, description, description_hash,
status, metadata_json` only. `requirements_json`, `preferred_qualifications_json`, `salary_*`,
`remote_status`, `employment_type`, `posted_at`, `source_url`, `apply_url` are **never updated**. So a
posting edited to add "7+ years" in `requirements` keeps stale requirements and stays eligible.
Also `status=excluded.status` blindly writes whatever the normalizer set (`NEW`), so re-discovery resets a
job to `NEW`; nothing compares old vs new `description_hash` to emit `UPDATED`/`UNCHANGED` (both enum
values are currently dead). **Required:** update all mutable columns; compute status by comparing stored
`description_hash`; emit a job-updated event that re-runs eligibility.

**Codex update:** `upsert_job` now refreshes mutable columns on rediscovery. Incremental status is computed in
the discovery pipeline before persistence.

### P2-2 — `UNIQUE(apply_url)` on `jobs` can crash discovery.
**File:** `app/database/schema.py:45`. Only `ON CONFLICT(source, external_job_id)` is handled in
`upsert_job`. Any two postings that normalize to the same apply URL (career-portal root, shared apply
landing) raise an unhandled `IntegrityError`. **Required:** drop `UNIQUE(apply_url)` (dedupe belongs in
the pipeline, P1-3) or handle that conflict explicitly.

**Codex update:** Fresh schema no longer declares `UNIQUE(apply_url)`. Repository also handles legacy local
databases that still have an old apply-url uniqueness constraint.

### P2-3 — No `human_tasks` table / no `resumes` write path.
`HUMAN_REQUIRED` is central but there is nowhere to enqueue the task (owner, reason, snapshot path,
created/closed, blocking question text). `SCHEMA.md` names `resumes` but `repository.py` has no insert for
it. **Required:** add `human_tasks` now; add `insert_resume` + `attach_resume_to_application`.

**Codex update:** Added `human_tasks`, `insert_resume_artifact()`, and `attach_resume_to_application()`.

### P2-4 — `FailureCategory` gaps.
Add `STALE_POSTING`, `POSTING_CLOSED`, `DUPLICATE`, `PROFILE_INCOMPLETE`, `TRUTH_VALIDATION_FAILED`,
`LOCATION_INELIGIBLE`, `WORK_AUTH_INELIGIBLE`. Align 1:1 with `FAILURE_MODEL.md` categories.

**Codex update:** Added these enum values.

### P2-5 — Job family classification is unimplemented; filters depend on it.
`role_taxonomy.yaml` keywords are loaded by nothing. `apply_hard_filters` first checks
`job.job_family.value not in accepted_families`, but `job_family` is set by an unimplemented normalizer.
This is the crux of "belongs to an accepted target family" from the PRIMARY PRINCIPLE — Phase 2 must
implement deterministic title/JD keyword classification with an `UNKNOWN` → keep-and-LLM path (do not drop
UNKNOWN).

**Codex update:** YAML taxonomy classification is implemented. Deterministic hard filters keep `UNKNOWN`
family jobs for later review rather than dropping them.

### P2-6 — `description_hash` over raw HTML is noisy.
**File:** `app/models/job.py:17,53`. Hash normalized visible text with collapsed internal whitespace, not
raw HTML, or trivial markup changes create false `UPDATED`.

**Codex update:** Supported source adapters now strip HTML before constructing `Job`, so the hash is based on
visible text for those sources.

---

### P3
- `application_state_transitions.created_at` uses `CURRENT_TIMESTAMP`; every other timestamp is Python
  tz-aware `.isoformat()`. Standardize on UTC ISO-8601 everywhere.
- `repository.connect()` commits on every non-exception exit even for reads; opens a connection per call.
  Fine now; revisit with a connection/transaction helper when workers scale.
- `SENIORITY_PATTERN` misses `II`/`III`/`L4`/`SDE 2`/`Level III`. Low value (these are rarely truly senior
  for new-grad families) but cheap to add.
- Add a module docstring to `truth_validation.py` stating it is a non-functional placeholder.

---

## Answers to Codex handoff questions

1. **State machine completeness / terminal states** — see P0-1. Add `VERIFIED` (only counted state) and
   `SUBMISSION_UNKNOWN`; `SUBMITTED` must not be terminal; add `* -> CLOSED`.
2. **SQLite constraints for dup prevention / history** — see P0-2 (`applications.dedupe_key UNIQUE`),
   P0-4 (FK pragma per connection), P2-2 (`UNIQUE(apply_url)` risk), P1-4 (CAS transition). History log is
   good; add `human_tasks` and `resumes` write paths.
3. **Hard-filter false positives (experience, clearance)** — confirmed: P1-1 (experience) and P1-2
   (clearance) both over-reject. Patches provided. Plus the *missing* filter P0-3 (sponsorship) and P1-7
   (US location).
4. **Candidate profile TODO handling / truth assumptions** — P1-6 (fact IDs + completeness gate) and P1-5
   (validator is a stub). Do not generate resumes or enable submission while TODOs remain.
5. **Adapter interface boundaries (GH/Lever/Ashby)** — interface in `app/applications/interfaces.py` is
   reasonable. Additions required: `verify_submission()` must return an evidence tier or UNKNOWN (not a
   bare bool — return `Verification{tier, evidence, status}`); `fill`/`answer_questions` must have an
   explicit CAPTCHA/MFA/unknown-question → HUMAN_REQUIRED path; `apply` must write the idempotency row
   first. Discovery interface: add an incremental `discover_changed_since(cursor)` and return
   `requisition_number`. Details in `ATS_MATRIX.md` §3 and `JOB_SOURCE_RESEARCH.md`.
6. **Test gaps before Phase 2** — added `tests/test_adversarial_*.py` (filters, dedup, state machine,
   truth). Several are `xfail(strict=False)` marking desired-but-missing behavior — treat each xfail as a
   P1/P2 to close. See `docs/FAILURE_MODEL.md` §7 for the full adversarial catalog.

---

## Re-review checklist (apply to each Codex PR)

- [ ] New ATS adapter implements `discover()`, `normalize()`, `apply()`, `verify_submission()`, plus a
      tested CAPTCHA/MFA/unknown-question → HUMAN_REQUIRED path.
- [ ] `apply()` writes the `applications.dedupe_key` row before touching the form.
- [ ] `verify_submission()` returns an evidence tier or UNKNOWN; nothing counts as VERIFIED without evidence.
- [ ] Every resume bullet / answer traces to `fact_id`s; validator runs; unknowns → HUMAN_REQUIRED.
- [ ] Deterministic filters (family, seniority, experience, sponsorship, location, clearance,
      employment-type) run before any LLM call.
- [ ] Failure paths emit structured events with a category from `FAILURE_MODEL.md`.
- [ ] New code has tests, including ≥1 adversarial case.
- [ ] No secrets/PII in logs or prompts beyond the minimum.
- [ ] All outbound HTTP goes through the shared rate-limited client (per-host + per-ATS buckets).
- [ ] `PRAGMA foreign_keys = ON` on every connection.

---

## Reference architecture (review baseline)

```
Company Registry ──(scheduled crawl)──> Discovery adapters (GH/Lever/Ashby/Workday/SR/Workable)
   │                                          │ raw postings
   │                                          v
   │                                    Normalizer ──> canonical Job + content_hash + requisition_number
   │                                          v
   │              Dedupe (exact source_id -> company+req -> simhash) + Eligibility pipeline:
   │              1 deterministic filters  2 cheap LLM extract (batch, small)  3 strong LLM (gated)
   │                                          v
   │                                  Application Queue (durable, idempotent, per-domain rate limit)
   │                                          v
   │        Application workers: persona -> resume build (fact-checked) -> fill -> submit -> VERIFY
   │                                          v
   │             Submission Ledger: APPLYING -> SUBMITTED -> VERIFIED | SUBMISSION_UNKNOWN | FAILED | HUMAN_REQUIRED
   │                                          v
   └───────────────────────────────  Observability + Human Review UI (human_tasks)
```

Open questions for Codex: stack confirmation (assume Python 3.12 + Playwright + SQLite→Postgres later);
single-box vs distributed workers (drives queue impl); is account creation in v1 (recommend no — GH/Lever/
Ashby first); where the human-review queue lives; confirmed candidate mailbox for verification polling.
