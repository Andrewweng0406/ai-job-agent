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

**Verification:** `python3 -m pytest -q` → **316 passed, 1 skipped**.

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
| Greenhouse DOM dry-run | **Fixed foundation.** `GreenhouseDryRunAdapter` captures DOM fields, maps through the canonical form engine, persists transcripts, routes hard stops, gates bad PDFs, and never calls submit in dry-run. |
| PDF upload gate | **Fixed foundation.** Bad resume validation blocks the resume field and produces `would_submit=false`; Greenhouse dry-run test proves no submit-ready path. |

### Still Deferred

- Controlled real submission remains deferred. `real_submission_enabled` stays `false`.
- Live Playwright navigation is next; browser capture and Greenhouse fixture-driven dry-run transcript generation are implemented first.
- Lever and Ashby DOM-driven dry-run adapters remain deferred until Greenhouse live dry-run navigation is stable.
