# ROUND2_5_CHECKLIST.md — Round 2.5 Verification Checkpoint

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Rule: DO NOT TRUST `CODEX_PROGRESS.md`.** For every item: (a) inspect the implementation, (b) run the
named test, (c) try to break it. Mark **PASS** only when behavior is *demonstrated*. Otherwise **OPEN**
with the failing evidence.

`real_submission_enabled` MUST remain `false` throughout. No real submissions.

---

## How to run

```
python -m pytest -q                       # full suite: record pass / xfail / xpass / fail
python -m pytest -q tests/test_workflow_idempotency.py tests/test_discovery_cas.py \
    tests/test_human_task_atomicity.py tests/test_worker_lease.py \
    tests/test_resume_numeric_provenance.py tests/test_sponsorship_adversarial.py \
    tests/test_submission_verification_adversarial.py -rA
```
Any **xpass** = a gap Codex closed → promote that test to a plain assertion and note it.

---

## A. P1-13 — Workflow persistence & idempotency

| # | Check | How to verify | Status |
|---|---|---|---|
| A1 | `run()` refuses unless DB status ∈ {READY, RETRY_PENDING} | `test_workflow_idempotency.py::test_run_rejects_non_runnable_states` (APPLYING/SUBMITTED/SUBMISSION_UNKNOWN/VERIFIED/FAILED/HUMAN_REQUIRED all rejected) | ☐ |
| A2 | Status check reads the **DB**, not the passed-in object | Pass a stale `Application(status=READY)` while DB says `SUBMITTED` ⇒ refused. `test_stale_object_loses_to_db` | ☐ |
| A3 | Every step transitions through the repository (ledger + `application_state_transitions` rows) | assert transition rows for `APPLYING` then `SUBMITTED` then terminal | ☐ |
| A4 | `attempt_count` incremented once per run; `applied_at` set | inspect row after `run()` | ☐ |
| A5 | Two concurrent `run()` on one application ⇒ only one proceeds | `test_two_run_calls_one_executes` (second returns `APPLICATION_NOT_READY`) | ☐ |
| A6 | Crash after submit, before verify ⇒ row recoverable in `APPLYING`/`SUBMISSION_UNKNOWN`, **no** second submit on restart | `test_crash_after_submit_no_duplicate` (adapter.submit call count == 1) | ☐ |
| A7 | `SUBMISSION_UNKNOWN` cannot re-enter `APPLYING` | graph reachability test still green | ☐ |

## B. P1-14 — Discovery / application-creation CAS

| # | Check | How | Status |
|---|---|---|---|
| B1 | N discovery workers see the same job ⇒ ONE `jobs` row, ONE `applications` row | `test_discovery_cas.py` at concurrency 2, 4, 8 | ☐ |
| B2 | No unhandled `RuntimeError("Concurrent status modification")` surfaces | run B1, assert `summary.errors == []` | ☐ |
| B3 | Same requisition via Greenhouse URL / search URL / tracking URL / canonical company URL ⇒ converge to one application | `test_discovery_cas.py::test_four_url_shapes_converge` | ☐ |
| B4 | `_incremental_status` no longer a separate connection before `upsert_job` (TOCTOU) | read `pipeline.py` / `repository.py`; single txn or `RETURNING` | ☐ |
| B5 | Second discovery run of an unchanged job ⇒ 0 new applications | `test_discovery_pipeline.py::test_discovery_pipeline_dedupe_key_prevents_second_application_for_same_requisition` (currently FAILING on Codex WIP — must go green) | ☐ |

## C. P1-15 — Numeric résumé entailment

| # | Check | How | Status |
|---|---|---|---|
| C1 | Number in a cited fact's text ⇒ SUPPORTED (valid) | `test_resume_numeric_provenance.py` supported cases | ☐ |
| C2 | Inflated number (`20%`→`35%`, `$12,000`→`$120,000`, `15+`→`50+`) ⇒ UNSUPPORTED (reject) | provenance reject cases | ☐ |
| C3 | Calendar years / version numbers / course numbers ⇒ NON-CLAIM, not validated as metrics, not rejected as "unsupported metric" | `test_non_claim_numbers_are_not_metrics` | ☐ |
| C4 | Percentages / currency / integers / decimals / ranges (`1-3`, `1–3`, `15+`) / counts / hours-per-week all handled | parametrized coverage | ☐ |
| C5 | No `fact_texts` provided ⇒ numeric claim is NOT silently accepted (fail-closed) | `test_missing_fact_texts_fails_closed` | ☐ |
| C6 | `OVERREACH_PATTERN` word-list is not the only guard — category lint documented as heuristic; entailment judge or HUMAN_REQUIRED for residual | inspect `truth_validation.py`; note if still word-list-only ⇒ OPEN as P1-12 residual | ☐ |

## D. P1-16 — Sponsorship / work-auth rule engine

| # | Check | How | Status |
|---|---|---|---|
| D1 | Compositional rule (negation window + concept), not a growing list of literal phrases | inspect `hard_filters.py`; count literal branches — if still climbing, OPEN | ☐ |
| D2 | Hard-negative corpus all ⇒ `NO_VISA_SPONSORSHIP` | `test_sponsorship_adversarial.py::hard_negatives` | ☐ |
| D3 | Ambiguous/positive corpus (`sponsorship may be available`, `case-by-case`, `OPT welcome`, `international graduates may apply`) ⇒ KEPT | `::ambiguous_kept` | ☐ |
| D4 | `citizenship preferred` ≠ `citizenship required` | `::citizenship_preferred_vs_required` | ☐ |
| D5 | ITAR / export-control / US-person / citizenship / PR / clearance are **distinct** rules, not collapsed | `::concepts_not_collapsed` (each concept maps to its own reason code) | ☐ |

## E. Profile completeness gate

| # | Check | How | Status |
|---|---|---|---|
| E1 | Any `required: true` fact = `TODO` ⇒ résumé generation refused | `test_*` on `profile_completeness_gate` | ☐ |
| E2 | Same ⇒ workflow `run()` returns `HUMAN_REQUIRED` (`PROFILE_INCOMPLETE`) regardless of `real_submission_enabled` | inspect `workflow.py` (already wired — confirm it reads the real profile) | ☐ |
| E3 | Gate is independent of `real_submission_enabled` (both must pass) | toggle in a test | ☐ |

## F. Structured submission verification

| # | Check | How | Status |
|---|---|---|---|
| F1 | `verify_submission()` returns a `VerificationEvidence`/tier, not a bare bool (bare `True` path deprecated) | inspect adapters + `workflow.py` | ☐ |
| F2 | Only T1–T4 ⇒ `VERIFIED`; T5 alone ⇒ stays `SUBMITTED` → `SUBMISSION_UNKNOWN` at window close | `test_submission_verification_adversarial.py` tier matrix | ☐ |
| F3 | HTTP 200 + validation-error text ⇒ NOT `VERIFIED` | `::http200_with_error_not_verified` | ☐ |
| F4 | Generic "Thank you" w/o application context ⇒ not strong evidence | `::generic_thanks_is_weak` | ☐ |
| F5 | Duplicate evidence merge ⇒ no duplicate transition/event rows | `::duplicate_evidence_idempotent` | ☐ |
| F6 | `SUBMISSION_UNKNOWN` + later T3 email ⇒ `VERIFIED` (transition legal) | `::unknown_promoted_by_email` | ☐ |
| F7 | `confirmation_data_json` populated with tier + ref on every `SUBMITTED`/`VERIFIED` | inspect row | ☐ |

## G. Shared HTTP client / rate limiting

| # | Check | How | Status |
|---|---|---|---|
| G1 | One client used by all adapters | grep for `JsonHttpClient(` / direct `urlopen` in `app/` | ☐ |
| G2 | Per-host + per-ATS token bucket | inspect `app/utils/http.py`; current implementation has a per-host throttle and bounded retry loop. Per-ATS buckets remain deferred until live ATS workers exist. | PASS / partial |
| G3 | Honors `Retry-After` on 429/503 | `test_http_client.py::test_retry_after_respected` | ☐ |
| G4 | Backoff has jitter; retries bounded; POST-like never auto-retried after send | inspect | ☐ |
| G5 | `User-Agent` identifies the project + contact | inspect config | ☐ |

## H. DB indexes & human-task atomicity

| # | Check | How | Status |
|---|---|---|---|
| H1 | Indexes present: `idx_applications_status`, `idx_transitions_app`, `idx_jobs_company_status`, `idx_jobs_incremental`, `idx_applications_claimable` | `PRAGMA index_list` in a test / read `schema.py` | ☐ |
| H2 | `human_tasks` partial unique `(application_id, category) WHERE status='OPEN'` | read schema; `test_human_task_atomicity.py::test_same_question_twice_one_task` | ☐ |
| H3 | Application→HUMAN_REQUIRED **and** task creation are one transaction (crash between ⇒ no orphan HUMAN_REQUIRED) | `test_human_task_atomicity.py::test_no_orphan_human_required` | ☐ |
| H4 | `mark_human_required` is a single `BEGIN IMMEDIATE` (transition + reason UPDATE together, one connection) | inspect `repository.py` | ☐ |
| H5 | Resolving a task requires current status still `HUMAN_REQUIRED` (CAS) | `test_human_task_atomicity.py::test_resolve_rejects_if_status_moved` | ☐ |

## I. Worker claims / leases (prep — layer may not exist yet)

| # | Check | How | Status |
|---|---|---|---|
| I1 | `worker_id`, `lease_expires_at`, `lease_epoch` columns + claimable index | read schema | PASS |
| I2 | Atomic claim: 2/4/8 claimers on one row ⇒ exactly one wins | covered by `tests/test_repository.py::test_claim_next_application_is_lease_protected`; higher-concurrency stress test still deferred | PASS / partial |
| I3 | Lease expiry ⇒ reclaim by another worker, `lease_epoch` bumped | `::test_lease_expiry_reclaim` | ☐ |
| I4 | Fencing: returning zombie worker fails `lease_still_mine` ⇒ `submit()` not called | lease fencing primitive covered by `tests/test_repository.py::test_claim_next_application_is_lease_protected`; worker integration deferred | PASS / partial |
| I5 | Reaper: `APPLYING` past grace, submit fired ⇒ `SUBMISSION_UNKNOWN`; not fired ⇒ `RETRY_PENDING` | `tests/test_worker_lease.py::test_reaper_routes_post_submit_crash_to_submission_unknown` and `::test_expired_lease_is_reclaimable_and_epoch_bumps` | PASS |
| I6 | No scenario yields two `→ SUBMITTED` transitions for one `application_id` | `::test_no_double_submit` | ☐ |

---

## Exit criteria for Round 2.5 sign-off

1. **A, C, E, F all PASS** — these are integrity gates. No exceptions.
2. **B PASS** OR `discovery_concurrency` pinned to 1 with a written note.
3. **I PASS** at the DB primitive/reaper layer. `application_concurrency` remains pinned to 1 until live
   Playwright worker integration tests exist.
4. **G2/G3** PASS before any adapter does live HTTP at scale.
5. Full suite green; every xpass promoted; new findings appended to `CLAUDE_REVIEW.md` with repro + patch
   + the test that should pass.
6. `real_submission_enabled` still `false`. Phase 4 proceeds as **dry-run only** until a human reviews
   ≥3 dry-run transcripts per ATS.
