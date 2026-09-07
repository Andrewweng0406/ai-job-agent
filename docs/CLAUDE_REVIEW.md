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

## Review round 1.5 — on top of `525ecae` ("Add human task and form field foundations")

**Re-reviewed:** `state_machine.py`, `workflow.py`, `pipeline.py`, `hard_filters.py`, `deduplication.py`,
`truth_validation.py`, `discovery/adapters.py`, `schema.py`, new `form_fields.py` / `human_tasks.py`.
**Tests:** `pytest -q` → 140 passed, 0 xfailed.

### Fixed since round 1 (verified)
| Ref | Status |
|---|---|
| P0-5 (unknown → re-submit launder) | **Fixed.** `SUBMISSION_UNKNOWN → {VERIFIED, SKIPPED, CLOSED}` only; no path back to `APPLYING`. |
| P1-8 (`SUBMISSION_UNKNOWN → VERIFIED`) | **Fixed.** Now legal; `SUBMITTED → {VERIFIED, SUBMISSION_UNKNOWN}`. |
| P1-9 (adapters drop posted date) | **Fixed** for Greenhouse/Lever/Ashby (source timestamp → `Job.posted_at`). |
| P1-9a (non-ASCII / "to" experience ranges) | **Fixed.** `1–5`, `1—5`, `3 to 5` now kept. |
| P1-10 (narrow sponsorship pattern) | **Fixed** for the tested phrasings — but see P1-16 (brittleness). |
| P1-11 (ITAR / "U.S. Person") | **Fixed.** New reason `EXPORT_CONTROL_RESTRICTED`. |
| P2-2 (`UNIQUE(apply_url)` hazard) | **Fixed.** Constraint removed. |
| P2-3 (`human_tasks` table) | **Landed.** `human_tasks` + `app/applications/human_tasks.py`. |
| DB-review #4 (application dedupe_key on surrogate `job_id`) | **Fixed.** Now `candidate_id | company_id | ATS/req_key` via `application_dedupe_key_for_job`. |
| P1-6 (completeness gate) | **Partial.** Missing `auth.needs_future_sponsorship` + no-sponsorship JD → `HUMAN_REQUIRED` (`WORK_AUTHORIZATION_PROFILE_INCOMPLETE`). Full gate (block all real submission while any `required` fact is TODO) still not enforced centrally. |

### Still open

#### P1-13 — `ApplicationWorkflowRunner.run()` still never persists / never guards idempotency. **(superseded: fixed in Codex Round 2 response below)**
**File:** `app/applications/workflow.py:29-58`. Confirmed unchanged: it mutates `application.status` in
memory and returns; no `repository.transition_application`, no check that the row isn't already
`SUBMITTED`/`VERIFIED`/`SUBMISSION_UNKNOWN` before driving the form, no `attempt_count`/`applied_at`.
Re-running a queued application ⇒ duplicate submit. This is the top remaining P1. Required fix unchanged
from round 1.5 first pass. Test: `tests/test_adversarial_workflow.py` (regression, currently marks the
gap).

#### P1-14 — Discovery insert/transition is still check-then-act. **(superseded: fixed in Codex Round 2 response below)**
**File:** `discovery/pipeline.py:78-95`. `if not application_exists_for_job(job_id): insert_application();
transition_application(ELIGIBLE)`. `insert_application` is idempotent, but with `discovery_concurrency: 2`
the losing worker's `transition_application` hits an already-advanced row ⇒
`RuntimeError("Concurrent status modification")` bubbles up as a company-level error. Use the insert's
returned id and only transition if the row is still `DISCOVERED` (CAS; swallow the benign race). Also
`_incremental_status()` still opens its own connection before `upsert_job` (TOCTOU on `description_hash`).

#### P1-15 — Entailment "fix" over-corrects: all numeric claims are now rejected. **(new)**
**File:** `truth_validation.py` `validate_with_provenance` — `if numbers: unsupported_numbers.extend(numbers)`.
Every digit-bearing claim is now invalid, even `"Analyzed 50,000 rows"` citing a real
`project.retail_dashboard` fact whose text contains "50,000". This will force every quantified bullet to
`HUMAN_REQUIRED` and pushes generation toward number-free (weaker) bullets. Plus `OVERREACH_PATTERN` is a
fixed word-list ("production", "senior", "expert", "managed a team", …) — it will miss inflations phrased
differently and false-positive on legitimate uses. **Required:** real per-claim checks — a number is
supported iff it appears in the text of a cited fact (normalize `50,000`/`50000`/`~50k`); skill/tool
tokens ⊆ cited facts; forbidden closed-set terms absent; residual NL → entailment judge or
`HUMAN_REQUIRED`. Tests: `tests/test_resume_redteam.py::test_legit_cited_number_is_accepted` (add).

#### P1-16 — Sponsorship / clearance patterns are becoming phrase-specific. **(new, watch)**
`NO_SPONSORSHIP_PATTERN` now has ~10 literal branches, several matching the exact adversarial strings
("will require sponsorship now or in the future will not be considered"). This passes the suite but is
brittle against real-world variance. **Recommended:** refactor to the compositional rule (negation window
+ `sponsor`-stem, AND-NOT positive) so new phrasings are covered without a new branch each time. Not a
blocker; track for a cleanup pass.

#### Carried forward (unchanged): P2-1 (lossy `upsert_job` update — `requirements_json`, `salary_*`,
`posted_at`, `employment_type` not refreshed on conflict), P2-5 (family classification is keyword-only;
`UNKNOWN` handling path), P2-7, P2-8, and the P3 list.

### DB / concurrency — remaining
- Indexes from the round-1.5 DB table still not added (`idx_applications_status`, `idx_transitions_app`,
  `idx_jobs_company_status`, `idx_jobs_incremental`). `get_applications_by_status` full-scans each tick.
- `human_tasks`: add the partial unique index `(application_id, category) WHERE status='OPEN'`.
- `mark_human_required` still does transition + a second UPDATE on a **separate connection** — wrap in one
  `BEGIN IMMEDIATE`.
- Add `worker_id` / `claimed_at` + a stuck-row reaper before raising `application_concurrency` above 1
  (see `THROUGHPUT_MODEL.md` §4 — the 1→3-4 bump is the biggest throughput unlock and is gated on P1-13,
  P1-14, and the reaper).

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

---

## Codex response — Round 2 / 2.5 blockers

**Verification:** `python3 -m pytest -q` → `252 passed`.

### Fixed

| Ref | Status |
|---|---|
| P1-13 workflow idempotency/state persistence | **Fixed.** `ApplicationWorkflowRunner` reads repository state before driving an application, refuses non-runnable states, persists transitions, increments `attempt_count`, sets `applied_at`, and distinguishes pre-submit `FAILED` from post-submit `SUBMISSION_UNKNOWN`. |
| P1-14 discovery check-then-act race | **Fixed.** Discovery now uses conflict-safe `insert_application()` with a requisition-derived dedupe key and transitions only the winning inserted application row. |
| P1-15 numeric resume entailment | **Fixed.** Numeric validation checks cited fact text, normalizes commas/decimals/`k` shorthand, supports years and ranges, and rejects unsupported numbers fail-closed. |
| P1-16 sponsorship negation brittleness | **Fixed for current blocking corpus.** Added a compositional hard-negative detector using negation windows around sponsor/sponsorship/work-visa terms while preserving positive/ambiguous sponsorship language. |
| P1-17 citizenship/permanent-resident variants | **Fixed.** Explicit citizenship, permanent resident, and green-card-only requirements now route to `US_CITIZEN_ONLY`; preferred language remains eligible. |
| Profile completeness independent of submit setting | **Fixed.** Required `TODO` facts block preparation/submission regardless of `real_submission_enabled`. |
| Structured verification evidence | **Fixed.** Adapters can return `VerificationEvidence`; T1-T4 promotes to `VERIFIED`, weak evidence is persisted without counting as success. |
| Shared HTTP safety | **Fixed.** Shared client has per-host rate limiting, timeouts, bounded retries, `Retry-After`, jittered backoff, headers, and warnings. |
| Worker lease/fencing primitives | **Fixed foundation.** Added `worker_id`, `claimed_at`, `lease_expires_at`, `lease_epoch`, transactional claim to `APPLYING`, `lease_still_mine()`, and `release_lease()`. |
| Dry-run transcript persistence | **Fixed foundation.** Added immutable `dry_run_transcripts` table and `DryRunTranscript` payload/hash model. |
| P1-19 human-task orphaning | **Fixed.** `mark_human_required()` synthesizes a minimal `HumanTask` when the caller omits one, and the status transition plus task write stay in one `BEGIN IMMEDIATE` transaction. |
| P1-20 cross-source application dedupe | **Fixed.** Application dedupe keys use source-neutral metadata requisition IDs or canonical apply-URL requisition IDs before falling back to ATS external IDs. |
| P1-18 stale worker reaper | **Fixed foundation.** Expired `APPLYING`/`TAILORING` leases are reaped with transition logs; pre-submit work returns to `RETRY_PENDING`, while rows marked `SUBMIT_POST_SENT` go to `SUBMISSION_UNKNOWN`. |

### Deferred

- Live browser form automation and real submission remain deferred until the dry-run transcript and approval path is complete.
- Live multi-worker orchestration is deferred until Playwright dry-run workers exist; the database reaper and fencing primitives are in place first.
- Provider-backed LLM tailoring is deferred behind deterministic prompt/eval contracts. Current tailoring is deterministic, JD-aware, and fact-ID constrained.

### Rejected

- None.

---

## Review round 2.5 — independent verification of Codex's Round 2 fixes + Phase 4 prep

**Reviewer ran (not trusting `CODEX_PROGRESS.md`):** full suite `pytest -q` → **235 passed, 2 xfailed**,
plus targeted verification suites added this round. Method per item: inspect code → run test → try to break.

**Codex follow-up:** promoted the two remaining xfails after fixing P1-19/P1-20, then added the P1-18
database reaper. Full suite now `python3 -m pytest -q` → **252 passed**.

### Verified PASS (behavior demonstrated by a reviewer-authored test)

| Fix | Evidence |
|---|---|
| **P1-13** workflow persistence + idempotency | `tests/test_workflow_idempotency.py`: `run()` refuses all 6 non-runnable states; **DB status wins over a stale `Application` object**; two `run()` calls ⇒ `submit()` once; crash-after-submit ⇒ `SUBMISSION_UNKNOWN`, restart does **not** re-submit. |
| **P1-14** discovery CAS | `tests/test_discovery_cas.py`: 2/4/8 concurrent `DiscoveryPipeline.run()` ⇒ 1 job row, 1 application row, `summary.errors == []`; same Greenhouse req via 4 tracking-URL variants across separate runs ⇒ 1 application. |
| **P1-15** numeric entailment | `tests/test_resume_numeric_provenance.py`: number ∈ cited fact text ⇒ SUPPORTED; `20%→35%`, `$12k→$120k`, `15+→50+` ⇒ rejected; ranges `1-3`/`1–3` handled; **no `fact_texts` ⇒ fail-closed**. |
| **P1-16** sponsorship variants | `tests/test_sponsorship_adversarial.py`: hard-negative corpus ("unable to sponsor employment visas", "no sponsorship is available", "cannot provide current or future sponsorship", "does not sponsor applicants") ⇒ `NO_VISA_SPONSORSHIP`; ambiguous/positive ("case-by-case", "OPT welcome", "international graduates may apply") ⇒ kept. |
| **P1-17** citizenship/PR variants | "U.S. citizenship required" (no "is"), "Requires US citizenship", "citizen or permanent resident", "permanent residency", "green card holders only" ⇒ `US_CITIZEN_ONLY`; "preferred" ⇒ kept. Distinct reason codes for ITAR / clearance / citizenship. |
| **Structured verification** | `tests/test_submission_verification_adversarial.py`: T1–T4 ⇒ `VERIFIED`; T5 alone ⇒ stays `SUBMITTED`; generic "Thank you" ⇒ `is_strong()==False`; duplicate strong evidence ⇒ 1 `VERIFIED` transition; `SUBMISSION_UNKNOWN` + later T3 email ⇒ `VERIFIED`. |
| **Worker claim / lease / fencing** | `tests/test_worker_lease.py`: 2/4/8 concurrent `claim_next_application` ⇒ exactly 1 winner; `lease_still_mine` true only for holder+epoch; expired lease ⇒ zombie fenced; `release_lease` clears ownership. |
| **Profile completeness gate** | `workflow.py` runs `profile_completeness_gate(profile)` before the `real_submission_enabled` check ⇒ `HUMAN_REQUIRED (PROFILE_INCOMPLETE)` independent of the submit flag. |
| **DB indexes / human-task partial-unique** | `schema.py`: `idx_applications_status`, `idx_applications_lease`, `idx_transitions_app`, `idx_jobs_company_status`, `idx_jobs_incremental`; `idx_human_tasks_open_unique (application_id, category) WHERE status IN ('OPEN','IN_PROGRESS')`. `mark_human_required(app, reason, task)` = one `BEGIN IMMEDIATE`. `test_human_task_atomicity.py`: same question twice ⇒ 1 open task. |

### Claimed fixed — NOT independently verified (needs a test)

| Item | Gap |
|---|---|
| **Shared HTTP client rate limiting / `Retry-After`** | `app/utils/http.py` has a per-host throttle + bounded retry, but there is **no test** for `Retry-After` handling, jitter, or "never auto-retry after a POST send". Add `tests/test_http_client.py` before any live HTTP at scale. Per-ATS buckets deferred. |

### New findings (open)

#### P1-18 — No reaper; a crashed application worker's row is unrecoverable. **(closed by Codex follow-up)**
`claim_next_application` only selects `status IN (READY, RETRY_PENDING)`. A worker that claims a row
(→ `APPLYING`), sets a lease, then crashes leaves it in `APPLYING` with an expired lease and **nothing
moves it back** — no reaper exists. **Required before `application_concurrency > 1`:** a reaper that
finds `APPLYING`/`TAILORING` rows with `lease_expires_at < now - grace` and routes them →
`RETRY_PENDING` (no submit fired) or `SUBMISSION_UNKNOWN` (submit fired). **Resolution:**
`JobAgentRepository.reap_expired_leases()` implements this behavior and
`tests/test_worker_lease.py` covers pre-submit, post-submit, and tailoring lease expiry.

#### P1-19 — `mark_human_required(app, reason)` with no task ⇒ unexplained `HUMAN_REQUIRED`. **(closed by Codex follow-up)**
`workflow.py` calls it without a `HumanTask` for `NO_SUPPORTED_APPLICATION_ADAPTER`, `PROFILE_INCOMPLETE`,
`REAL_SUBMISSION_DISABLED`. Those applications land in `HUMAN_REQUIRED` with **no `human_tasks` row** —
invisible to the operator queue. `tests/test_human_task_atomicity.py::test_no_orphan_human_required_when_task_is_omitted`
is now a plain passing regression test. **Resolution:** `mark_human_required` synthesizes a minimal task
when none is passed.

#### P1-20 — Application `dedupe_key` varies with `job.source`. **(closed by Codex follow-up)**
`application_dedupe_key_for_job(job, candidate_id)` folds in the ATS `source` label, so the same
requisition seen under a different `source` (greenhouse vs company-site mirror vs aggregator) ⇒ a
different key ⇒ a **second application to the same real job**.
`tests/test_discovery_cas.py::test_same_requisition_via_different_source_labels_converges` (now plain passing).
**Required:** key on `candidate_id | canonical_company_id | requisition_key` only (ATS-stable req id via
`deduplication._extract_req_id` / adapter metadata) — never the `source` string. (Same point as
round-1.5 DB review item #4; the discovery path still leaks `source`.)

### Phase 4 readiness (browser / real application layer)

- New design docs for Codex to build against: `APPLICATION_FORM_ENGINE.md`, `BROWSER_ATS_STRATEGY.md`,
  `DRY_RUN_DESIGN.md`, `WORKER_CONCURRENCY.md`, `LLM_RESUME_REVIEW_CONTRACT.md`, `PDF_RESUME_QA.md`.
- Throughput (`THROUGHPUT_MODEL.md` §8): 100 verified/day at 60–75% attempt→verified and 4–6 min form
  time ⇒ ~135–170 attempts/day, **3–4 application workers**, ~1,000–1,600 boards, 2 resume + 2 verify
  workers. `application_concurrency` still remains 1 until live Playwright dry-run worker integration is
  tested; the P1-18 database reaper is now implemented.
- **Do not enable `real_submission_enabled`.** Phase 4 is dry-run-only until a human reviews ≥3 dry-run
  transcripts per ATS.

### Round 2.5 checkpoint

`docs/ROUND2_5_CHECKLIST.md` A–I with exact test names. A/C/E/F/B and worker-lease **PASS** (demonstrated);
P1-18 reaper is implemented, but `application_concurrency` stays 1 until live worker integration tests
exist; G2/G3 need `tests/test_http_client.py`. `real_submission_enabled` stays `false`.

---

## Review round 3 — Phase 4 implementation (incremental)

**Reviewed at `6bbe19c` + uncommitted form-engine/dry-run WIP.** Full suite: **294 passed, 1 skipped,
5 xfailed** (xfails = the open findings below). New reviewer tests: `tests/test_form_engine_redteam.py`,
`tests/test_dry_run_consistency.py`, `tests/test_pdf_qa.py`, `tests/test_browser_capture_hardstop.py`.
Checklist: `docs/ROUND3_CHECKLIST.md`.

### Verified PASS (reviewer test demonstrates it)

| Area | Evidence |
|---|---|
| **P1-18 reaper** | `reap_expired_leases()`: `APPLYING`+`SUBMIT_POST_SENT` note → `SUBMISSION_UNKNOWN`; else `APPLYING`/`TAILORING` → `RETRY_PENDING`; CAS + `BEGIN IMMEDIATE` + logged transition. `tests/test_worker_lease.py`. |
| **P1-22** legal-question routing (raised + fixed this round) | Only a tight `sponsorship` Y/N pattern auto-answers from the bank; every other legal / work-auth / citizenship / "employer support" / "open source" label → `HUMAN_REQUIRED`, never an invented value. `tests/test_form_engine_redteam.py`. |
| **P1-23** SELECT option mapping (raised + fixed this round) | A resolved value not present in `field.options` → `HUMAN_REQUIRED`/`FORM_MAPPING`, not a silent fill. |
| **P1-21** résumé validation gate (raised + fixed this round) | `FormDryRunEngine.build_transcript(..., resume_validation_status=…)`: a non-`PASS` artifact → the résumé field is not `FILLED`; dry run → `HUMAN_REQUIRED`. `tests/test_dry_run_consistency.py::test_dry_run_blocks_when_resume_not_validated`. |
| Dry-run never submits | `build_transcript` returns `READY`/`HUMAN_REQUIRED` only; no adapter/`submit()` call. `would_submit` computed, not adapter-set. Unresolved required field → `human_tasks` row + `would_submit=False`. |
| Transcript determinism | identical inputs → identical `payload["fields"]`. |
| CAPTCHA / MFA hard stop (capture level) | CAPTCHA/MFA/`recaptcha/api.js` HTML → 0 fields extracted, `blocking_reasons`, `human_required=True`, screenshot saved. No solver anywhere in `app/`. `tests/test_browser_capture_hardstop.py`. |
| LLM résumé truth | **N/A — no bullet generator exists.** `JdAwareTailoringPlanner` only selects `fact_id`s and excludes `literal_only`/missing facts. Fabrication is not currently possible. Forward contract stands (`LLM_RESUME_REVIEW_CONTRACT.md`). |

### New findings — open

#### P1-24 — "submit was sent" is signalled by a substring in the free-text `notes` column. **(open)**
**File:** `app/database/repository.py` `reap_expired_leases` — routes `APPLYING` → `SUBMISSION_UNKNOWN`
only if `"SUBMIT_POST_SENT" in (notes or "")`, else → `RETRY_PENDING`. `notes` is a general-purpose
free-text field other code also writes. If the browser adapter fails to set that exact string
immediately before the submit click (or another writer clobbers it), a post-submit crash is routed to
`RETRY_PENDING` ⇒ **duplicate submission** — the precise failure the reaper exists to prevent.
**Fix:** dedicated column `submit_attempted_at TEXT` (or `submit_epoch INTEGER`), set in the same
transaction as the "about to click submit" step; reaper checks that column, not `notes`.
**Test:** extend `tests/test_worker_lease.py` — set `submit_attempted_at`, crash, reap → `SUBMISSION_UNKNOWN`;
without it → `RETRY_PENDING`.

#### P2-9 — `FormDryRunEngine` opens one human task for `blocking_reasons[0]` only. **(open)**
**File:** `app/applications/form_engine.py` `build_transcript`. Unresolved fields spanning ≥2 categories
(e.g. `PROFILE_INCOMPLETE` + `FORM_MAPPING`) produce a single task; the operator resolves it and the
re-run is still blocked by the other category. **Fix:** one `HumanTask` per distinct category in
`blocking_reasons` (the partial-unique index already supports it). **Test:**
`test_dry_run_multi_category_unresolved_opens_a_task_per_category`.

#### P2-10 — Transcript payload missing `persona` / `requisition_key`; no approval-hash enforcement. **(open)**
`build_transcript` payload has `job`, `resume`, `fields`, `unresolved`, `would_submit` — but no
`persona`, no `requisition_key`, and `dry_run_transcripts` has `payload_hash` but no `approved_by/at`
and no code that re-checks the hash before a (future) submit. Per `DRY_RUN_DESIGN.md` §2/§5. Track now
since browser submit is next.

#### P2-11 — `render_simple_pdf` silently corrupted content; no PDF-QA module. **(fixed in-round)**
Raised: `line[:110]` truncation, non-latin-1 → `?`, single `/Page` with no pagination/overflow signal,
no gate. Codex added `app/resumes/pdf_qa.py` and reworked `app/resumes/pdf.py`; `tests/test_pdf_qa.py`
guards are now plain assertions. Still to verify at the next checkpoint: failing QA →
`validation_status=PDF_QA_FAILED` → application `HUMAN_REQUIRED` and the PDF never reaches an upload
field (end-to-end wiring, not just the module).

#### P2-12 — Bot-wall detection & state wiring. **(detection fixed in-round; state wiring open)**
**File:** `app/applications/browser_capture.py`. Codex added tokenless-challenge detection (Cloudflare
Turnstile / `cf-challenge`) — `test_turnstile_widget_without_captcha_token_is_detected` now passes.
**Still open:** `BrowserCaptureResult.human_required` is returned but **no application-state transition
happens** — the hard stop is not yet wired to `mark_human_required(category=CAPTCHA|MFA|EMAIL_VERIFICATION,
task=…)`; and "verification code" is labelled `MFA` even when it is email verification.

#### P2-13 — Radio groups become N separate `BOOL` fields. **(open)**
**File:** `app/applications/html_form_extractor.py` `_kind_for` maps every `type=radio` to `BOOL`, and
each radio input is emitted as its own field. A "Sponsorship: (Yes) (No) (Decline)" group → 3 fields
with the same label, each resolved and "FILLED". **Fix:** coalesce `type=radio` sharing a `name` into
one `SELECT` field whose `options` are the radio labels.

#### P2-14 — Custom-question labels not captured when the ATS omits `<label for>`. **(open)**
**File:** `html_form_extractor.py` `_label_for` falls back to `aria-label` → `placeholder` → `name` →
preceding text. Greenhouse/Lever/Ashby custom questions frequently use a `<div class="label">` or
`<legend>` with the input inside a wrapper and no `for`. Those land with an ugly `name`-attribute
"label" → `classify_label` returns `None` → `HUMAN_REQUIRED` (safe but noisy; kills throughput on
otherwise-answerable questions). **Fix:** capture `<legend>` and the nearest preceding block-level text
/ `[class*=label]` sibling.

#### P2-15 — Single-token name → last-name field `FILLED` with `""`. **(open)**
**File:** `app/applications/form_fields.py` `resolve_value` — `personal.last_name` returns `""` when the
full name has one token. A required last-name field then submits blank / fails ATS validation. **Fix:**
`HUMAN_REQUIRED` when the name cannot be split.

#### P3 — `StaticAtsFieldProvider` field lists are hand-written guesses; salary/relocation always `HUMAN_REQUIRED`.
Dry runs today do not reflect a real posting's DOM. Replace with `BrowserFieldCapture` + per-ATS
fixtures. Add `compensation.*` / `location.relocation` specs so questions with a canonical answer don't
needlessly page the operator.

### Phase 4 readiness

Not ready for controlled real submission. Blockers before that decision: P1-24 (submit-attempted flag),
P2-11 (PDF QA gate), P2-9 (multi-category tasks), P2-12 (hard-stop state wiring), and at least one real
fixture-driven ATS adapter dry run that stops before submit, verified by a spy adapter. `real_submission_enabled`
stays `false`; controlled submission remains a separate human decision after ≥3 reviewed dry-run
transcripts per ATS.

---

## Codex response — Round 3 follow-up

**Verification:** `python3 -m pytest -q` → **329 passed, 1 skipped**.

### Fixed

| Ref | Status |
|---|---|
| P1-21 resume validation gate | **Fixed.** `FormDryRunEngine` accepts `resume_validation_status`; invalid/non-passing artifacts block the resume field with `TRUTH_VALIDATION_FAILED`. `ApplicationDryRunPreparer` passes the persisted resume validation status from the database. |
| P1-22 legal/source routing | **Fixed.** Legal/work-authorization auto-answering is restricted to tight known authorization/sponsorship phrasings. Novel legal labels and source-code/open-source labels route to human/skip rather than canned answers. |
| P1-23 select option mapping | **Fixed.** Select/multi-select fields validate the resolved value against options and only use conservative sponsorship/authorization mappings; unmappable values become `FORM_MAPPING`. |
| P1-24 submit attempted marker | **Fixed.** Added `submit_attempted_at`, repository `mark_submit_attempted()`, workflow marking before submit, and reaper logic based on that dedicated column instead of free-text `notes`. |
| P2-9 multi-category human tasks | **Fixed.** Dry-runs now open one human task per distinct blocking category. |
| P2-10 transcript payload/approval foundation | **Fixed foundation.** Transcript payload includes `persona` and source-neutral `requisition_key`; repository approval/hash helpers are available for future submit gating. |
| P2-11 PDF QA | **Fixed foundation.** PDF rendering no longer truncates lines, paginates long content, applies ASCII-safe punctuation fallback, and the generator runs `pdf_qa` before producing a validated artifact. |
| P2-12 bot-wall detection | **Fixed at capture level.** Browser capture now detects Turnstile/Cloudflare challenge markers in addition to CAPTCHA/MFA text tokens. Live worker state wiring remains deferred until Playwright workers exist. |
| P2-13 radio groups | **Fixed.** Same-name radio controls are coalesced into one select-like field with options. |
| P2-14 custom labels | **Fixed foundation.** HTML extraction now prefers nearby question text before machine `name` attributes. |
| P2-15 single-token name | **Fixed.** Required last-name derivation blocks with `PROFILE_INCOMPLETE:name.full` instead of filling an empty string. |
| HTTP client proof | **Fixed.** Added `tests/test_http_client.py` covering per-host throttle, bounded GET retries, 429/503, Retry-After seconds/date, timeout wrapping, and no blind POST retry. |
| P2-12 hard-stop state wiring | **Fixed foundation.** `persist_browser_hard_stop()` transitions the application to `HUMAN_REQUIRED` and opens category-specific CAPTCHA/MFA/EMAIL_VERIFICATION tasks. |
| Greenhouse/Lever/Ashby DOM dry-run | **Fixed foundation.** Shared ATS DOM adapters capture fields, map through the canonical form engine, persist transcripts, route hard stops, gate bad PDFs, and never call submit in dry-run. |
| PDF upload gate | **Fixed foundation.** Bad resume validation blocks the resume field and produces `would_submit=false`; Greenhouse dry-run test proves no submit-ready path. |
| Approval-gated autofill preview | **Fixed foundation.** Preview rendering requires approved transcripts, recomputes payload hash, rejects not-submit-ready transcripts, and exposes a read-only CLI command. |
| Dry-run worker integration | **Fixed foundation.** READY applications are transactionally claimed, stale workers abort before page access or transcript writes, successful no-submit runs return to READY, and the worker rejects `real_submission_enabled=True`. `tests/test_dry_run_worker.py`. |

### Still Deferred

- Controlled real submission remains deferred. `real_submission_enabled` stays `false`.
- Greenhouse live Playwright navigation foundation is implemented; exercising it against reviewed public postings is next.
- Live Lever and Ashby navigation remains deferred until Greenhouse live dry-run navigation is stable.

## Codex Phase 4.2 safety closure

**Verification:** `python3 -m pytest -q` -> **374 passed, 1 skipped**.

- P1-25, P1-26, and P1-27 are fixed and promoted to passing red-team tests.
- P1-28 is mitigated for the live preview path: autofill requires explicit `human_invoked=True`,
  performs a post-fill hard-stop scan, and remains outside any submission-capable worker.
- P2-18 is fixed with deterministic EEO decline-option matching.
- P2-20 is fixed: only 429 and transient 5xx responses are retried; ordinary 4xx responses fail fast.
- Live Greenhouse evidence is recorded in `docs/greenhouse_live_dry_run_report.json` with a retained
  screenshot under `artifacts/`; the run discovered 24 fields and invoked submit zero times.

Remaining: approved-transcript autofill integrated into a submission-capable worker, richer DOM-origin
provenance for every field, and additional reviewed live runs. Real submission remains disabled.

---

## Review round 3.1 — Greenhouse real-DOM red team

**Reviewed at `34902ed` + uncommitted WIP** (`browser_autofill.py`, extractor/hard-stop refactor).
Suite: 360 passed, 1 skipped, 8 xfailed, **3 failing on Codex WIP** (`test_ats_dom_dry_run`,
`test_autofill_preview`, `test_browser_hard_stop_state` — Codex mid-refactor). New reviewer tests:
`tests/test_greenhouse_realdom_redteam.py`, `tests/test_submit_guard.py`,
`tests/test_submission_boundary.py`, fixture `tests/fixtures/ats_forms/greenhouse_application.html`.
Checklist: `docs/ROUND3_1_CHECKLIST.md`.

### Verified PASS
- **P1-24** submission boundary: durable `applications.submit_attempted_at` column; reaper routes
  `APPLYING`+`submit_attempted_at` → `SUBMISSION_UNKNOWN`, else → `RETRY_PENDING`; `SUBMISSION_UNKNOWN`
  reaches no submit-permitting state. `tests/test_submission_boundary.py`.
- **HTTP client**: `tests/test_http_client.py` proves `Retry-After` (numeric + HTTP-date), 429/5xx retry,
  bounded retries, per-host spacing, timeout wrap, and **POST is never blind-retried**.
- **PDF→upload gate** (form-engine level): non-`VALIDATED` résumé → field `BLOCKED`, `would_submit=False`,
  `submit_call_count==0`. Autofill also hash-checks the file before `set_input_files`.
- **radio→select coalescing** and **`<legend>` labels**: Yes/No group → one `select`, not two BOOLs.
- **submit guard**: `AtsDomDryRunAdapter.submit()` raises+counts; `FormDryRunEngine` never submits; live
  runner refuses `real_submission_enabled=True`; `DryRunBrowserAutofill` has no submit method; and it
  runs a **transcript↔browser differential** (`BROWSER_TRANSCRIPT_MISMATCH` if the field's post-fill
  value ≠ the resolved value).
- **bot-wall**: CAPTCHA/MFA/Turnstile/`cf-challenge` → 0 fields + `persist_browser_hard_stop` →
  `mark_human_required(category, task)` + screenshot path. No solver, no retry.
- **lease/reaper in the dry-run worker**: `lease_still_mine` re-checked around navigation and before the
  final transition; `LEASE_LOST` → no side effect.
- **transcript**: `persona` now in payload; `ApprovedAutofillPreviewBuilder` enforces approval +
  `sha256(payload_json)==payload_hash` + `would_submit` before surfacing autofill values.

### Rejected / not demonstrated
- **Greenhouse real-DOM milestone: NOT genuinely complete.** `GreenhouseLiveDryRunRunner` *can* drive
  real Playwright and refuses `real_submission_enabled`, but **every test injects a fake page** and there
  is **no capture/fixture from a live Greenhouse apply page** and no artifact proving a real navigation.
  Architecturally ready; not proven. Do not accept as the milestone.

### New findings — open

#### P1-25 — `submit_attempted_at` is never cleared; `claim_next_application` doesn't guard on it. **(latent P1)**
Only the reaper consumes the column. When a real submit worker lands it must (a) set it transactionally
immediately before the submit click, and (b) the claim/worker must refuse any row where it is non-null
(except via the verify path). Otherwise a stale non-null value on a row that later returns to a
claimable state permits a second submit. `tests/test_submission_boundary.py::test_stale_submit_attempted_on_a_reREADY_row_is_guarded` (xfail).

#### P1-26 — Honeypot / hidden field is extracted (and mislabeled). **(open)**
**File:** `app/applications/html_form_extractor.py`. `extract()` skips only `type ∈ {hidden, submit,
button, reset}`. A Greenhouse honeypot `<input name="job_application[hp_email]" style="display:none"
aria-hidden="true" tabindex="-1">` is extracted as a fillable `text` field (label bleeds to `'No'` from
the preceding radio). Filling a honeypot = instant bot flag / auto-reject. **Fix:** skip inputs with
`aria-hidden="true"`, `type="hidden"`, `tabindex="-1"`, or `style` containing `display:none`/
`visibility:hidden`, or a `hidden` attribute, or a class Greenhouse uses for hidden fields.
**Test:** `tests/test_greenhouse_realdom_redteam.py::test_honeypot_field_is_excluded` (xfail).

#### P1-27 — Dry-run autofill sends `locator.press("Enter")` on a live form. **(open)**
**File:** `app/applications/browser_autofill.py` — combobox branch does `locator.fill(value);
locator.press("Enter")`. `Enter` in a field inside `<form>` can trigger implicit submission. The dry run
must never send a submitting keypress. **Fix:** use `select_option` / an explicit option-element click /
JS `value` set + `dispatchEvent('change')`; never `press("Enter")`/`press("Return")` on a live page.
**Test:** `tests/test_submit_guard.py::test_dry_run_autofill_never_presses_enter_or_keys_that_can_submit` (xfail).

#### P1-28 — Autofill path is unfenced and runs on an unapproved transcript. **(open)**
`GreenhouseLiveDryRunRunner` → `DryRunBrowserAutofill.apply(...)` runs **outside** the lease-fenced
`DryRunApplicationWorker`, on `adapter_result.dry_run.resolutions` directly (no `approved_by/at` check —
`ApprovedAutofillPreviewBuilder` is a different path), and does **no post-fill hard-stop re-check**
(typing can trigger a behavioral bot challenge). **Fix:** fold autofill into the fenced worker + require
an approved transcript, or demote this path to an explicit human-invoked preview with a re-check after
fill.

#### P2-16 / P2-17 — `aria-labelledby` resolved only positionally; unlabeled inputs bleed the previous
control's text (`'*'`, `'No'`). Resolve `aria-labelledby` / `aria-describedby` by id; when no label can
be found, emit an empty label (→ HUMAN_REQUIRED) rather than the neighbour's text.

#### P2-18 — EEO decline doesn't match real ATS option wording. **(open)**
`"Decline to self-identify"` ≠ `"Decline To Self Identify"` / `"I don't wish to answer"` /
`"I do not want to answer"`, so P1-23 option-mapping sends **every EEO field → HUMAN_REQUIRED**,
defeating the always-auto-decline default and paging the operator on every application. **Fix:** map
decline intent to whichever option contains `decline|wish|want|prefer not` or the empty-value option,
case-insensitively. **Test:** `tests/test_greenhouse_realdom_redteam.py::test_eeo_fields_auto_decline_against_real_option_wording` (xfail).

#### P2-20 — HTTP `get_json` retries on all `HTTPError` incl. 4xx; retry only 429/500/502/503/504.

#### P3 — extractor: field order not preserved (radio-group fields appended); placeholder `-- Select --`
kept in `options`; trailing ` *` left in labels.

### May Codex proceed to Lever?
Not yet. Close the Greenhouse P1s (P1-26, P1-27, P1-28) and demonstrate a real capture first. Lever/Ashby
already share `AtsDomDryRunAdapter` + `HtmlFormFieldExtractor`, so every finding here applies to them.
`real_submission_enabled` stays `false`.

---

## Review round 3.2 — verifying the "first live Greenhouse run"

**At `dc766fc`, clean tree, 392 passed / 1 skipped / 4 xfailed.** New reviewer tests:
`tests/test_round32_regressions.py`. Checklist: `docs/ROUND3_2_CHECKLIST.md`.

### Verified FIXED
- **P1-25** — `claim_next_application` now has `AND submit_attempted_at IS NULL` (READY + RETRY_PENDING);
  only `-> SKIPPED` clears the marker. A row that may have crossed the submission boundary cannot be
  re-claimed for a fresh attempt. `tests/test_round32_regressions.py`.
- **P1-27** — `locator.press("Enter")` removed from `browser_autofill.py`; no `press`/`Return`/
  `requestSubmit`/`form.submit()`/submit-event/`keyboard.press` anywhere in the browser/autofill path.
- **P2-18** — `_map_select_value` `eeo_decline` branch matches `decline|prefer not|wish|want`; verified
  against 5 real ATS wordings; a field with no safe decline option is never `FILLED` with a real value.
- **P2-20** — HTTP client retries only 429/500/502/503/504; 400/401/403/404/422 -> exactly 1 call.

### Partial / still open
- **P1-26 -> P2-21** — `_is_noninteractive` catches `display:none`/`visibility:hidden`/`aria-hidden`/
  `tabindex=-1` (the common Greenhouse honeypot is now excluded) but misses bare `hidden` attr,
  `disabled`, offscreen (`left:-9999px`), `opacity:0`. `tests/test_round32_regressions.py::test_other_hidden_field_techniques_are_also_excluded` (xfail).
- **P1-28 (still open)** — live-autofill path (`GreenhouseLiveDryRunRunner` -> `DryRunBrowserAutofill`)
  gained a `human_invoked=True` gate and a **post-fill hard-stop re-check** (good), but still has **no
  lease fencing** (no `lease_still_mine` checks; `autofill.apply` loops all fields with no re-check) and
  drives from an **unapproved** transcript (`ApprovedAutofillPreviewBuilder` is a separate unused path).
- **P2-22 (new)** — the "first live run" is a manual non-reproducible one-off. No committed script,
  `test_greenhouse_live.py` still mocks, nothing in CI navigates a real page, and the run archived only
  `docs/greenhouse_live_dry_run_report.json` (aggregate, hand-writable) + one JD-fold screenshot. No
  sanitized DOM capture, no field map, no browser-action log, no `run_id`/ISO `captured_at`.

### Gate G — **FAIL (real navigation, not independently auditable)**
The screenshot `artifacts/greenhouse_anthropic_4461450008.png` is a genuine render of the live Anthropic
Greenhouse posting (Account Executive, AI Native) -> a real browser navigated a real current page, and
the Playwright code path is genuine. But the evidence bundle Gate G requires does **not** exist: no
sanitized DOM/HTML, no field map, no browser-action log, no safety report. Field-origin audit (§11) and
browser-action audit (§12) cannot be performed. `final_submit_invocation_count: 0` and no implicit
submission vector remain in the code, but "reviewable evidence" is missing. **Gate G is not closed.**

### May Codex proceed to Lever?
**No.** Close P1-28, land P2-21, and produce a reproducible live-run script + full archived artifact
bundle (P2-22). No new P0. `real_submission_enabled` stays `false`.

---

## Review round 3.3 — final Greenhouse Gate G audit

**HEAD = `60985ce` (my R3.2 commit). No Phase 4.3 follow-up exists** — newest Codex commit is `9088c37`
(post-fill hard-stop re-capture only). Suite: 392 passed / 1 skipped / 4 xfailed / 0 failed.
Checklist: `docs/ROUND3_3_CHECKLIST.md`.

### New this round (positive)
Reviewer did an **independent read-only Playwright navigation** to
`https://job-boards.greenhouse.io/anthropic/jobs/4461450008` (no app code, no interaction beyond
`goto`+`content`): HTTP 200, title "Job Application for Account Executive, AI Native at Anthropic",
1 `<form>`, 29 `<input>`, 3 `<textarea>`, contains `first_name`/`last_name`/`resume`/`sponsorship`/
`authoriz`/`submit application`. ⇒ the page Codex navigated in `dc766fc` **was a real live Greenhouse
application form.** Navigation authenticity: independently CONFIRMED.

### Still FAIL — unchanged since R3.2
- **P1-28 lease fencing — absent.** `GreenhouseLiveDryRunRunner.run()` has no `lease_still_mine` /
  `worker_id` / `lease_epoch`; `autofill.apply` mutates the live page with zero lease checks.
- **P1-28 approval gate — absent.** `grep ApprovedAutofillPreviewBuilder|approved_by` over
  `greenhouse_live.py` + `browser_autofill.py` → no match. Autofill runs from the just-built
  `resolutions`; `human_invoked=True` is the only gate. Unapproved / expired / tampered-payload /
  changed-resume-hash / changed-answers all currently drive live fill.
- **P2-21** — `_is_noninteractive` unchanged (misses `hidden` attr / `disabled` / offscreen / `opacity:0`).
- **P2-22** — `scripts/` is empty; `artifacts/` holds one JD-fold PNG. No `dom.sanitized.html`,
  `field_map.json`, `browser_actions.jsonl`, `safety.json`, `transcript.sanitized.json`, before/after
  form screenshots, `run_id`, or ISO `captured_at`. Field-traceability (§8), honeypot-exclusion (§9),
  browser-action (§11), transcript/browser-diff (§12), lease-trace (§13), approval-trace (§14) audits
  are all impossible.

### Truthfully N/A — PASS
- Resume upload: `resume_upload_call_count: 0`, profile TODO-backed ⇒ HUMAN_REQUIRED; report states it, no overclaim.
- PII: only the Anthropic-JD PNG + an aggregate report.json are committed; no email/phone/address/token/
  résumé text; profile still 20× TODO.
- Submit: `final_submit_invocation_count: 0`; no implicit submit primitive in code (re-verified). But
  the unfenced/unapproved autofill means a future misuse is not *structurally* prevented.

### Gate G — **FAIL**
Real navigation is now independently confirmed. Every other core requirement is unmet: no DOM capture,
no field map, no action log, no lease fencing, no approval gate, incomplete artifact bundle.

### New P0: none.  New P1: P1-28 (both halves still open).

### May Codex proceed to Lever / Ashby? **No.** Blockers: P1-28, P2-21, P2-22.
`real_submission_enabled` stays `false`.

---

## Review round 3.4 — reproducible Greenhouse evidence bundle (autonomous mode)

**At `5acdeb9`** (Codex `dee8e92` bundle + `5acdeb9` hidden-field hardening). Suite: 407 passed /
1 skipped / 5 xfailed. Reviewer tests: `tests/test_round34_evidence_audit.py`. Checklist:
`docs/ROUND3_4_CHECKLIST.md`.

### Verified FIXED
- **P2-21** — `_is_noninteractive` now excludes `hidden` attr / `disabled` / `aria-hidden` /
  `display:none` / `visibility:hidden` / `opacity:0` / `tabindex=-1`+hidden-class / offscreen
  `position:absolute;left:-9xxx`. `tests/test_round32_regressions.py` P2-21 cases pass.
- **P2-22** — reproducible `scripts/live_dry_run.py` + archived bundles now exist.

### Independently verified (bundle is genuine)
- `dom.sanitized.html` (105 KB) is a real live Greenhouse capture: real Anthropic font assets, the real
  `candidate-ai-guidance` link, the embedded Greenhouse form-descriptor JSON, role-specific question
  text. Matches the reviewer’s own Round 3.3 navigation.
- All **24** `field_map.json` entries trace by label/selector into the captured DOM; custom questions
  carry real `question_########` ids; sponsorship question present + required; arbitration fields →
  HUMAN_REQUIRED.
- `browser_actions.jsonl` — ordered, time-sorted, `lease_epoch`-stamped, NAVIGATE/SCAN/EXTRACT/
  POST_FILL_SCAN only, no submit token. `safety.json` — submit 0, mismatch 0.

### Gate G — **FAIL (near miss)**
Real navigation + traceable DOM + reproducible script are in place. Blocked on P1-28 and the absence of
an *approved-autofill* run (the archived run is capture-only: `attempted_field_count: 0`,
`approval_status: not_approved_capture_only`), so the live transcript↔browser differential and the
runner-side approval/lease path are still unexercised.

### Open findings
- **P1-28 (P1, open)** — lease fencing is decorative (`lease_epoch` stamped, `lease_still_mine` never
  called) and the approval gate lives only in `scripts/live_dry_run.py`, not in
  `GreenhouseLiveDryRunRunner` (`human_invoked=True` is its sole guard).
- **P2-23** — raw `run.sqlite3` committed x4 (`.gitignore` has `*.sqlite3`; force-added). PII-clean only
  because the profile is TODO.
- **P2-24** — before/after screenshots are the JD fold (1280x720 top of page), not the form region;
  `before_fill.png` is byte-identical to the original JD screenshot; no fill occurred.
- **P2-25** — `transcript.sanitized.json` is a raw `json.dumps` of the payload — no redaction, no marker.
- **P2-26** — `_sanitize_html` redacts any 10+ digit run → the Greenhouse job id `4461450008` and CDN
  cache-busters become `[REDACTED_PHONE]`; and it does nothing for names/addresses/tokens.
- **P3** — 4 near-dup bundles (~1.5 MB); base bundle missing `report.json`; `dom.sanitized.html` is
  React-hydration-timing-dependent (only ~5 native inputs captured); `disabled` required fields now
  silently dropped by the extractor.

### No new P0. May NOT proceed to Lever/Ashby. `real_submission_enabled` stays `false`.

---

## Review round 3.4b — audit of Codex `6020308` ("Harden auditable Greenhouse evidence runs")

Suite: 437 passed / 1 skipped / 4 xfailed / 1 xpassed. Reviewer test: `tests/test_gate_g_remaining_gaps.py`.

### Verified FIXED
- **P2-23** — `.gitignore += artifacts/**/run.sqlite3`; all 4 `run.sqlite3` removed from git.
- **P2-25** — `scripts/live_dry_run.py::_sanitize_payload` redacts `legal_sensitive` + email/phone
  values and stamps `transcript.sanitized.json` with `"sanitized": true`.
- **P2-26** — `_sanitize_html` phone regex anchored to real phone shapes; v5 `dom.sanitized.html`
  keeps the job id `4461450008` and has **0** `REDACTED_PHONE` (was over-redacting the req id + CDN
  cache-busters).
- **P2-27 / P2-28** (shared-ATS) — Codex un-xfailed the Lever/Ashby label-bleed + radio-option tests;
  `tests/test_shared_ats_redteam.py` now passes.
- **P1-28 (plumbing)** — `GreenhouseLiveDryRunRunner` now: `_assert_lease()` → `lease_still_mine()` →
  `RuntimeError("LEASE_LOST")` at start / before nav / after nav / before autofill / after autofill;
  and autofill **requires** `approved_transcript_id`, validated via `ApprovedAutofillPreviewBuilder.build()`.

### Still open
- **P1-28b (P2)** — `_assert_lease` returns silently when `worker_id`/`lease_epoch` are `None`, so the
  fencing is opt-in. When `autofill=True` the runner should **require** a lease identity, not skip the
  check. Test: `test_gate_g_remaining_gaps.py::test_autofill_path_requires_a_lease_identity` (xfail).
- **P1-28c (P2)** — `DryRunBrowserAutofill.apply()` has no per-field/per-batch lease callback; a lease
  lost mid-fill still fills the remaining fields (`_assert_lease` only brackets the whole `apply()`).
- **GATE G (still FAIL — one blocker)** — every committed bundle (base/v2/v3/v4/v5) is
  `approval_status: not_approved_capture_only`, `attempted_field_count: 0`, `upload_performed: false`.
  The approved-autofill path is now built and gated but **has never been exercised on the live page**,
  so lease-fencing-during-fill, the transcript↔browser differential (`mismatch_count` is trivially 0),
  and a real before/after form screenshot pair are all still unevidenced. Test:
  `::test_an_approved_autofill_bundle_exists_with_exercised_differential` (xfail).
- **P2-24b** — v5 `before_fill.png` (141 KB) is a plain viewport shot, not a `#application_form` region
  capture (`after_fill.png` is 1.8 MB full-page ✓). And capture-only runs have no real before/after.
- **P3** — pre-fix bundles (base/v2/v3/v4) still carry the over-redacted DOM / unsanitized transcript;
  keep only the fixed v5 (or regenerate all). Base bundle also lacks `report.json` and a traceable job
  id in its DOM.
- **P3** — `_sanitize_payload` does not redact `name.full` / `contact.address.*` (not `legal_sensitive`,
  not in the key list).

### Gate G verdict: **FAIL — one substantive blocker left** (an *exercised* approved-autofill live run).
Everything else for Greenhouse is in place. **Not yet clear to start Lever/Ashby live work.**
`real_submission_enabled` stays `false`.

---

## Review round 3.4c — audit of Codex `287b577` ("Fence autofill mutations and harden shared labels")

Suite: 463 passed / 1 skipped / 2 xfailed.

### Verified FIXED
- **P1-28b** — `greenhouse_live.py`: `if payload.autofill and (worker_id is None or lease_epoch is
  None): raise RuntimeError("Live autofill requires worker lease identity")`. Fencing is no longer
  opt-in for the autofill path.
- **P1-28c** — `DryRunBrowserAutofill.apply(..., lease_check=Callable)` now calls `lease_check()` before
  **every individual field**, wired to `self._assert_lease(payload)`. A lease lost mid-fill aborts with
  `LEASE_LOST` and the remaining fields are not touched.
- **P2-27 / P2-28** — Lever/Ashby label bleed + Yes/No radio-group options fixed in
  `html_form_extractor.py`; `tests/test_shared_ats_redteam.py` all pass (Codex removed the xfails).

### P1-28 is now fully closed for Greenhouse
`GreenhouseLiveDryRunRunner`: refuses `real_submission_enabled`; requires `worker_id` + `lease_epoch`
when `autofill=True`; requires `approved_transcript_id` and validates it via
`ApprovedAutofillPreviewBuilder.build()` (approval + payload_hash + would_submit); `_assert_lease` →
`lease_still_mine` → `RuntimeError("LEASE_LOST")` at start / pre-nav / post-nav / pre-fill / per-field /
post-fill; post-fill hard-stop re-capture → HUMAN_REQUIRED.

### Gate G — **FAIL, one blocker remaining**
Every finding raised in rounds 3.2–3.4b is now closed **except**: no committed bundle is an *exercised*
approved-autofill run (`approval_status: approved`, `attempted_field_count > 0`, `mismatch_count: 0`,
`submit_invocation_count: 0`) with a real `#application_form` before/after screenshot pair. The path is
built, gated, and fenced — it needs to be run once with `--approved-by` and the bundle committed.
Codex can do this without user input (`real_submission_enabled` stays `false`; profile is TODO so
only AUTO_SAFE fields — e.g. EEO decline, "how did you hear" — would fill, which is enough to exercise
the differential).
Tests: `tests/test_gate_g_remaining_gaps.py::test_an_approved_autofill_bundle_exists_with_exercised_differential`,
`::test_before_and_after_screenshots_are_form_region_and_differ` (xfail).

### New this round
- `tests/test_legal_question_matrix.py` — 23-case shared-ATS legal/work-auth/citizenship/clearance/
  salary/relocation resolution matrix (all pass). This is the audit baseline for every future
  Lever/Ashby live run: a legal question is never auto-answered with an invented value.

`real_submission_enabled` stays `false`. May NOT start Lever/Ashby live work until the Gate G blocker
above is evidenced.

---

## Review round 3.5 — OSS provenance + `scripts/live_dry_run.py` audit (autonomous)

**At `8d73220`.** Suite: 469 passed / 1 skipped / 2 xfailed. Reviewer tests:
`tests/test_provenance_review.py`, `tests/test_live_dry_run_script_audit.py`.

### Open-source reference / provenance — REVIEWER-VERIFIED PASS (with P3 notes)
- All three repos in `THIRD_PARTY_NOTICES.md` **independently confirmed to exist and be MIT-licensed**
  (WebFetch): `idea-torx/CareerWeaver` (Python, MIT), `muhammad-saadd/applyai` (JavaScript Chrome
  extension, MIT), `AkbarDevop/ai-job-agent` (JS+Python, MIT). The referenced upstream files exist.
- `86c3b5e` added **only 4 doc/test files, zero `app/` code**.
- The repo contains **no `.js`/`.mjs` files** — the two JS references could not have been code-copied.
- The codebase history is fully incremental (reviewed commit-by-commit across rounds 1–3.4); nothing
  reads as a paste. The "concepts reimplemented, no code copied" claim is credible and consistent.
- **P3** — the notices should quote each upstream `LICENSE` copyright line verbatim (WebFetch could
  not confirm the exact holder names) and note whether the pinned commit hashes were HEAD-at-review.

### LLM / model-router safety — N/A
No model-router or provider-SDK code exists (`grep` for anthropic/openai/litellm/langchain → none).
`app/llm/tailoring.py` is the deterministic planner only. The standing contracts
(`LLM_RESUME_REVIEW_CONTRACT.md`, `LLM_COST_STRATEGY.md`) apply when a generator lands.

### `scripts/live_dry_run.py` — the evidence-producing tool bypasses the hardened runner
Codex extended the script to `--ats {greenhouse,lever,ashby}` and added `_write_blocked_bundle` (full
evidence on a CAPTCHA/bot-wall hard stop — good). But the script **reimplements the browser flow
inline and never uses `GreenhouseLiveDryRunRunner`**, so the P1-28 hardening is absent from the path
that will produce the Gate-G approved-autofill bundle:

- **P1-29** — `DryRunBrowserAutofill().apply(page, resolutions, expected_resume_hash="")` is called
  **without `lease_check=`**. The per-field lease fencing (P1-28c) is bypassed in the evidence path.
- **P1-30** — the script never calls `lease_still_mine` / `_assert_lease` after the initial claim.
  No lease fencing around nav / capture / autofill / screenshot.
- **P1-30b** — the `POST_FILL_SCAN` action is logged but nothing is re-captured or checked; there is
  **no post-fill bot-wall detection** (no `BrowserFieldCapture().capture()` / `persist_browser_hard_stop`
  after autofill).
- **P1-31** — `safety.json` hardcodes `attempted_field_count: 0`, `matched_field_count: 0`,
  `mismatch_count: 0` **even when `--approved-by` autofill ran**. The transcript↔browser differential
  in the evidence bundle would be a fabricated zero. `report.json.auto_safe_count` reflects the fill
  count; `safety.json` does not.
- **Fix:** route the script through `GreenhouseLiveDryRunRunner` (and Lever/Ashby equivalents once they
  exist), passing `worker_id`/`lease_epoch`/`approved_transcript_id`; compute `safety.json` from the
  real `BrowserAutofillResult` (attempted = len(resolutions filled), matched/mismatch from the
  `BROWSER_TRANSCRIPT_MISMATCH` comparison).

### P2-31 — no synthetic-vs-real candidate-profile separation
`CandidateProfile` built with plausible test data ("Jane Q Student") is structurally identical to a
real one. Nothing marks a profile as `synthetic_test` and nothing refuses such a profile in
`scripts/live_dry_run.py` / a future submit path. Today the only mitigation is that the real profile
is all-`TODO`. **Fix:** `CandidateProfile.source in {"config","synthetic_test"}`; the live script and
submit path refuse `synthetic_test`.

### P2-32 — `pdf_qa.run_pdf_qa`: `b"?" in content_stream` false-positives
A résumé bullet containing a literal `?` ("Why us?") → `UNSUPPORTED_TEXT_REPLACEMENT` → PDF_QA_FAILED →
HUMAN_REQUIRED. The check should compare against expected text or look for the specific latin-1
replacement pattern, not any `?`.

### Lever / Ashby status — NOT LIVE-EVIDENCED
`--ats lever|ashby` dispatch exists; the adapters are the shared `AtsDomDryRunAdapter`. **No committed
Lever or Ashby evidence bundle exists** (the `phase-lever-slate` / `phase-ashby-harvey` dirs were
transient and discarded). IMPLEMENTED (dispatch) but not TESTED against a live page, not LIVE-EVIDENCED.

`real_submission_enabled` stays `false`.

---

## Review round 3.6 — PII safety, first approved-autofill attempt (CAPTCHA), LLM router

### PII — RESOLVED
The candidate filled `config/candidate_profile.yaml` (name/email/phone/LinkedIn/school) — a tracked
file in a repo that pushes to GitHub. Fixed in `155f8e3`/`f9992ea`: real values moved to a gitignored
`config/candidate_profile.local.yaml`; tracked profile restored to the all-TODO template;
`apply company.py` + `scripts/live_dry_run.py` auto-prefer `.local.yaml` when no explicit path given;
`tests/test_pii_guard.py` (5 guards). Verified: git history contains **no** prior commit of the real
values; no tracked file contains the real email / phone / LinkedIn / address. **P3:**
`tests/test_form_engine.py` uses the literal string the real candidate name as a fixture name (name-only, no
linkage) — Codex should switch it to an obviously-fake name.

### First approved-autofill Gate-G attempt — hit a CAPTCHA, stopped correctly, NO PII typed
`artifacts/phase-greenhouse-anthropic-approved-20260907/` (uncommitted, incomplete). The run seeded a
Greenhouse "Software Engineer" application, claimed a lease, navigated — and **Anthropic's Greenhouse
served a CAPTCHA / bot-wall to headless Chromium**. `run.sqlite3` shows `APPLYING -> HUMAN_REQUIRED`
(reason CAPTCHA) 2 s after nav, one open `CAPTCHA` human task, **0 dry_run_transcripts** — so
`DryRunBrowserAutofill().apply()` was never reached and **no candidate PII was typed into the live
form**. `dom.sanitized.html` contains 0 PII (captured pre-fill). The hard-stop safety worked.

**Findings from this attempt:**
- **P2** — `scripts/live_dry_run.py::_write_blocked_bundle` (added in `8d73220` to persist evidence on a
  hard stop) is **dead code**: the earlier `if transcript is None: raise SystemExit(...)` (inside the
  `with sync_playwright()` block) pre-empts the `_write_blocked_bundle` call that follows the block. On
  a CAPTCHA you get a `SystemExit` and a partial dir (`before_fill.png` + `dom.sanitized.html` +
  `run.sqlite3`), not the intended blocked-evidence bundle. Fix: replace the `raise SystemExit` with the
  `_write_blocked_bundle` path (or move the block-write inside the `with`).
- **Operational** — Anthropic's `job-boards.greenhouse.io` now bot-walls headless Chromium. A live
  *approved-autofill* Gate-G run must target a **non-bot-walled** Greenhouse posting (or accept that
  this provider is HUMAN_REQUIRED end-to-end). The reviewer's earlier plain navigations succeeded, so
  the wall is intermittent / heuristic.
- The incomplete `phase-greenhouse-anthropic-approved-20260907/` dir should be deleted (it holds an
  uncommitted `run.sqlite3`).
- **Gate G — still FAIL.** No exercised approved-autofill bundle exists. P1-29/30/31 (script bypasses
  the fenced runner + fakes `safety.json` zeros) remain open and MUST be fixed before a real approved
  run, because that run WILL type the real `.local.yaml` name/email/phone into a live employer form.

### `app/llm/router.py` (`a258faf`) — IMPLEMENTED + TESTED, no live provider
Fail-closed boundary. **Working guards** (`tests/test_llm_router_audit.py`, 6 pass): mandatory Stage-0
gate (`LLM_STAGE0_GATE_REQUIRED`), empty/oversized prompt rejection, output-token cap to policy,
fail-closed daily budget when a cost is declared, negative-cost rejection.
**Gaps (xfail):**
- **P2** — cost is **caller-supplied**; `estimated_cost_usd=0.0` bypasses the budget entirely
  (`0 + 0 > limit` is False). The router should derive cost from `(model, input_chars, output_tokens)`
  via a price table, not trust the caller.
- **P2** — `spent_usd` is per-instance/in-memory; the "daily" budget resets every process. Needs
  date-keyed persistence (DB).
- **P3** — `stage` / `model` are free strings; no model-tier enforcement (a cheap "stage 1" can be
  routed to an expensive model — `LLM_COST_STRATEGY.md`: never invert tiers). No provider-side rate
  limiting / Retry-After. No per-stage sub-budgets. No `LLMRouter` consumer exists yet.

`real_submission_enabled` stays `false`.

---

## Review round 3.7 — verifying `bd673cb` / `931d78d` / `83978b8` (autonomous)

Suite: 500 passed / 1 skipped / 7 xfailed / 1 xpassed. Reviewer test: `tests/test_live_dry_run_lease_ttl.py`.

### Codex claims — verified
| Claim | Verdict |
|---|---|
| P1-29 per-field `lease_check` | **REVIEWER-VERIFIED PASS** — `apply(..., lease_check=lambda: _lease_check(...))`; `_lease_check` → `repo.lease_still_mine` → `RuntimeError("LEASE_LOST")`. |
| P1-30 lease around nav/capture/autofill/post-fill | **PARTIAL** — only per-field (in `apply`) + pre-post-fill. `page.goto`, pre-fill `capture`, `adapter.dry_run` are still **not** lease-checked. Risk (typing PII) is fenced; the claim is broader than the code. |
| P1-30b post-fill re-scan | **IMPROVED** — re-captures + logs `human_required`; `83978b8` also folds failed-action reasons (incl. `LEASE_LOST`) into `report.json.blocking_reasons`. Still: does not transition to HUMAN_REQUIRED / open a task on a post-fill wall; `post_fill_hard_stop` is hardcoded `True` in the blocked bundle (**P3** now that `blocking_reasons` is honest). |
| P1-31 runtime `safety.json` differential | **PASS (happy path)** — `attempted/matched_field_count` = real fill count, `mismatch_count` from a `BROWSER_TRANSCRIPT_MISMATCH`. On an actual mismatch the script `raise`s and the bundle is not written (**P2**). |
| P2 dead `_write_blocked_bundle` (`931d78d`) | **FIXED** — `transcript is None` no longer `raise SystemExit`; the blocked-bundle path runs. Hard-stopped runs now produce a full auditable bundle (see v4). |
| P2-31 synthetic profile source | **IMPLEMENTED, wrong direction** — enforces "`--test-only` ⇒ synthetic profile"; does **not** stop a real `--approved-by` run from typing the real `.local.yaml` PII into a live form. |

### NEW P1 — the evidence script self-`LEASE_LOST`s every run
**`scripts/live_dry_run.py:55`** — `repo.claim_next_application(ApplicationStatus.READY, worker_id,
`datetime.now(timezone.utc))` claims the lease with a **0-second TTL** (`timedelta` is not even
imported). Before `931d78d` nothing checked the lease so it did not matter; now that `_lease_check`
is wired, **every run fails `_lease_check` after the first slow browser op → `LEASE_LOST` → blocked
bundle**. Verified in `artifacts/phase-greenhouse-anthropic-approved-20260907-v4/browser_actions.jsonl`:
`NAVIGATE`(22:29:19) → `SCAN_HARD_STOP`(22:29:42, **23 s** later) → `EXTRACT_FIELDS`(24 fields, real DOM,
**no CAPTCHA**) → **`LEASE_LOST`**(22:29:43). The tooling can no longer produce a passing
transcript/autofill bundle. **Fix:** `datetime.now(timezone.utc) + timedelta(minutes=10)` (and import
`timedelta`); renew the lease around slow ops if needed.
**Test:** `tests/test_live_dry_run_lease_ttl.py::test_evidence_lease_is_claimed_with_a_real_ttl` (xfail).

### OPEN P1 — no guard against typing real PII into an arbitrary live form
`--approved-by` + the auto-preferred real `config/candidate_profile.local.yaml` + any `--url` = the real
name/email/phone typed into that live employer form. No URL allowlist, no per-run acknowledgment, no
refusal when the profile is `real`. **Required before any real approved run:** `--approved-by` must
require (a) `--url` on a user-confirmed allowlist OR an explicit `--i-am-applying-to-this-job` flag,
AND (b) refuse `profile_source=synthetic_test_only` on the autofill path.
**Test:** `tests/test_live_dry_run_lease_ttl.py::test_approved_autofill_requires_an_explicit_url_acknowledgment` (xfail).

### Status
- **Greenhouse Gate G — still FAIL.** Two blockers: the 0-TTL lease bug (every run LEASE_LOSTs) and the
  missing approval-URL guard. Anthropic's Greenhouse is intermittently reachable (v4 got 24 real fields,
  no CAPTCHA) — so once the lease TTL is fixed, a capture bundle is achievable; an *approved* one still
  needs the P1 URL guard.
- Lever / Ashby — `--ats` dispatch only; no live run.
- `real_submission_enabled` stays `false`. Local `.local.yaml` PII still unpushed / safe.

---

## Review round 3.8 — resume generator audit + PII name scrub (autonomous)

Suite: 505 passed / 1 skipped / 8 xfailed.

### `DeterministicResumeGenerator` — safe, near-non-functional. No P0/P1.
- **Fail-closed gates work:** incomplete profile → `PROFILE_INCOMPLETE`; missing required education fact
  → `REQUIRED_RESUME_FACT_MISSING`; PDF QA fail → `PDF_QA_FAILED`. Verified.
- **Output is verbatim profile facts** — `bullets` are extracted from the rendered selected-fact list,
  which is `profile.supported_fact_text(selected_fact_ids)`. Nothing is paraphrased → nothing can be
  fabricated. `render_simple_pdf` no longer truncates (earlier P2-11 fix confirmed: a 160-char bullet
  round-trips through `pdf_qa`).
- **P2** — `_render_sections` emits only `header` (name) / `target` / `education` / a flat selected-fact
  bullet list. There is **no experience / projects / skills section**, and the fact-ID model does not
  carry those types, so a real deterministic résumé is name + education + a few fact strings. The rich
  `projects`/`experience`/`leadership` in the legacy YAML block is unused by the generator.
- **P3** — `validate_claims_against_profile(bullets, fact_text)` with `bullets` derived from `fact_text`
  is a self-check; `validation_status="VALIDATED"` is asserted without an independent comparison (safe
  for a verbatim generator, but the label overstates what was checked).
- Tests: `tests/test_resume_generator_audit.py`.

### PII — real name was leaking into tracked files
`74babfc` ("Record canonical candidate identity") and earlier commits put the literal candidate name
into `docs/REAL_CANDIDATE_PROFILE_BLOCKERS.md`, `docs/CODEX_PROGRESS.md`, `tests/test_form_engine.py`
fixtures (×3), and — my own mistake — `docs/CLAUDE_REVIEW.md`. **Scrubbed from all tracked files**
(name → "Test Candidate" / "their name"); `tests/test_pii_guard.py` strengthened to also derive the
name needle from `config/candidate_profile.local.yaml` so any re-introduction fails.
- The name **remains in git history** (commit content and historical commit metadata). A `git
  filter-repo` rewrite would break every review SHA; the real mitigation is **making the GitHub repo
  private** — flag for the user.
- **P3 for Codex** — stop putting the real name in tracked docs/tests; use "Test Candidate".

### Still open (unchanged from 3.7)
- **P1** `scripts/live_dry_run.py` 0-second lease TTL — every evidence run self-`LEASE_LOST`s.
- **P1** `--approved-by` has no URL allowlist / acknowledgment — would type real `.local.yaml` PII
  into an arbitrary live form.
- Greenhouse Gate G FAIL; Lever/Ashby not live-run. `real_submission_enabled` stays `false`.
