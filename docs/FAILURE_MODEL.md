# FAILURE_MODEL.md — Failure Categories & Recovery

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Premise:** the system will attempt hundreds of applications. Most individual steps will fail sometimes.
The design goal is that **no failure silently becomes a false "submitted"**, and no failure causes a
**duplicate** submission.

---

## 1. Principles

1. **Fail closed on integrity, fail open on eligibility.** Unknown legal/authorization answer → stop.
   Ambiguous "is this new-grad?" → keep in queue (PRIMARY PRINCIPLE).
2. **Every failure has a category + a recovery policy + an owner** (system-retry vs human).
3. **Idempotency before side effects.** The `applications.dedupe_key` row exists before any form load.
4. **Unknown submission state is its own outcome**, never rounded to success or to a retryable failure.
5. **Evidence-based success only.** `VERIFIED` requires an evidence tier (`ATS_MATRIX.md` §4).
6. **Bounded retries with backoff + jitter.** Retries only for transient, side-effect-free failures.

---

## 2. Failure taxonomy

Legend — **Owner:** SYS (auto) / HUMAN. **Retry:** none / N with backoff / after human. **Terminal state.**

### A. Discovery & normalization
| # | Failure | Detection | Category | Owner | Recovery | End state |
|---|---|---|---|---|---|---|
| A1 | Duplicate job (same source id) | dedupe exact key | `DUPLICATE` | SYS | drop, link source_url to canonical | n/a |
| A2 | Near-duplicate (cross-source / repost) | company+req / simhash | `DUPLICATE` | SYS | merge into canonical job | n/a |
| A3 | Stale posting (discovered, now 404/closed) | re-fetch before apply | `STALE_POSTING`/`POSTING_CLOSED` | SYS | mark job CLOSED, skip application | CLOSED / SKIPPED |
| A4 | Bad JD parse (empty/garbled/truncated) | length + structure heuristics | `OTHER` (parse) | SYS→HUMAN if repeats | re-fetch once; if still bad, keep raw, tag `parse_low_confidence`, allow LLM | ELIGIBLE or HUMAN_REQUIRED |
| A5 | Wrong job family classification | confidence < threshold | n/a (not a failure) | SYS | route to LLM classify; UNKNOWN → keep | ELIGIBLE |
| A6 | Non-US / ineligible location | location normalizer | `LOCATION_INELIGIBLE` | SYS | skip; keep if location unknown | SKIPPED |
| A7 | JD updated after discovery (adds "7+ yrs", clearance) | content_hash change → re-run filters | varies | SYS | re-evaluate; may move ELIGIBLE→SKIPPED | SKIPPED / ELIGIBLE |
| A8 | Source rate-limited / 429 | HTTP status | `RATE_LIMIT` | SYS | honor Retry-After, backoff, resume cursor | n/a |
| A9 | Source schema/endpoint changed | schema validation on response | `ATS_CHANGED` | HUMAN | pause that source, alert, keep others running | n/a |

### B. Eligibility / matching
| # | Failure | Detection | Category | Owner | Recovery | End state |
|---|---|---|---|---|---|---|
| B1 | Senior role mislabeled entry-level | seniority pattern on title + LLM check | (filtered) | SYS | SKIPPED reason `SENIORITY_TOO_HIGH` | SKIPPED |
| B2 | Experience req buried deep in JD | requirements-region scan + LLM extract | (filtered) | SYS | SKIPPED `EXPERIENCE_REQUIREMENT_TOO_HIGH`; ambiguous → keep | SKIPPED / ELIGIBLE |
| B3 | "Citizenship required" vs "preferred" | pattern distinguishes required/only vs preferred | (filtered) | SYS | required → SKIPPED `US_CITIZEN_ONLY`; preferred → keep | SKIPPED / ELIGIBLE |
| B4 | "No sponsorship" language | `NO_SPONSORSHIP_PATTERN` and not positive | (filtered) | SYS | SKIPPED `NO_VISA_SPONSORSHIP` | SKIPPED |
| B5 | Clearance required | clearance-context pattern | (filtered) | SYS | SKIPPED `INCOMPATIBLE_SECURITY_CLEARANCE` | SKIPPED |
| B6 | Wrong persona selected | persona map miss / family UNKNOWN | `OTHER` | SYS→HUMAN | family UNKNOWN + no persona → HUMAN_REQUIRED | HUMAN_REQUIRED |

### C. Resume / answer generation
| # | Failure | Detection | Category | Owner | Recovery | End state |
|---|---|---|---|---|---|---|
| C1 | Bullet not traceable to a fact_id | truth validator (entailment) | `TRUTH_VALIDATION_FAILED` | SYS | regenerate ≤2x with tighter constraints; still failing → HUMAN_REQUIRED | HUMAN_REQUIRED |
| C2 | Fabricated skill/number (e.g. "AWS", "2M rows") | unsupported-claim + number check | `TRUTH_VALIDATION_FAILED` | SYS | strip claim / regenerate; persistent → HUMAN_REQUIRED | HUMAN_REQUIRED |
| C3 | Required info omitted (graduation date, degree) | required-field presence check | `OTHER` | SYS | regenerate with mandatory section; fail → HUMAN_REQUIRED | HUMAN_REQUIRED |
| C4 | Resume render/PDF error | exception / 0-byte / unopenable | `OTHER` | SYS | retry render once; fail → HUMAN_REQUIRED | HUMAN_REQUIRED |
| C5 | Profile incomplete (TODO facts needed) | completeness gate | `PROFILE_INCOMPLETE` | HUMAN | block; open human task listing missing fact_ids | HUMAN_REQUIRED |
| C6 | LLM API error / timeout / quota | SDK error | `NETWORK`/`RATE_LIMIT` | SYS | backoff + retry ≤3; then leave QUEUED for next cycle | QUEUED |

### D. Account / auth (Workday, iCIMS, …)
| # | Failure | Detection | Category | Owner | Recovery | End state |
|---|---|---|---|---|---|---|
| D1 | Account creation fails (field reject, dup email) | form error / no confirmation | `ACCOUNT_CREATION` | SYS→HUMAN | retry once with vari/alias mailbox; else HUMAN_REQUIRED | HUMAN_REQUIRED |
| D2 | Email verification link needed | "verify your email" screen | `ACCOUNT_CREATION` | SYS (own mailbox) | poll candidate mailbox, click link once; timeout → HUMAN_REQUIRED | HUMAN_REQUIRED |
| D3 | MFA / phone code / authenticator | MFA prompt detected | `MFA` | HUMAN | screenshot + HUMAN_REQUIRED; never bypass | HUMAN_REQUIRED |
| D4 | Login fails (creds rotated / locked) | login error | `LOGIN` | SYS→HUMAN | 1 retry; lockout → HUMAN_REQUIRED, cool-down tenant | HUMAN_REQUIRED |

### E. Form fill / submit
| # | Failure | Detection | Category | Owner | Recovery | End state |
|---|---|---|---|---|---|---|
| E1 | CAPTCHA / bot wall | challenge element / block page | `CAPTCHA` | HUMAN | screenshot + HUMAN_REQUIRED; no solver; cool down source/IP | HUMAN_REQUIRED |
| E2 | Unknown custom question (not in bank, low classifier conf) | question classifier < 0.95 | `CUSTOM_QUESTION` | HUMAN | HUMAN_REQUIRED with the verbatim question | HUMAN_REQUIRED |
| E3 | Unknown legal/authorization question | legal-question detector | `CUSTOM_QUESTION` | HUMAN | **always** HUMAN_REQUIRED, never auto-answer | HUMAN_REQUIRED |
| E4 | Dropdown / option mismatch (no matching value) | option set vs intended value | `FORM_MAPPING` | SYS→HUMAN | fuzzy-map with allowlist; no safe match → HUMAN_REQUIRED | HUMAN_REQUIRED |
| E5 | Dynamic / multi-step form step not recognized | step signature unknown | `ATS_CHANGED` | HUMAN | HUMAN_REQUIRED + snapshot; flag adapter | HUMAN_REQUIRED |
| E6 | Resume upload rejected (type/size/parse) | upload error / re-render loop | `RESUME_UPLOAD` | SYS→HUMAN | retry with PDF/A, smaller; fail → HUMAN_REQUIRED | HUMAN_REQUIRED |
| E7 | Required field the adapter can't fill | validation error on submit | `FORM_MAPPING` | SYS→HUMAN | HUMAN_REQUIRED | HUMAN_REQUIRED |
| E8 | Validation error returned by ATS post-submit | error banner after submit | `VALIDATION_ERROR` | SYS | if no submission occurred: fix + retry within attempt cap | RETRY_PENDING / HUMAN_REQUIRED |
| E9 | Network error / timeout **before** submit click | exception, no POST sent | `NETWORK` | SYS | retry ≤3 backoff; then RETRY_PENDING for next cycle | RETRY_PENDING |
| E10 | Network error / timeout **immediately after** submit click | exception after POST fired | `SUBMISSION_UNKNOWN` | SYS→verify | **do NOT retry**; enter SUBMISSION_UNKNOWN; run verify loop | SUBMISSION_UNKNOWN |
| E11 | Submit clicked, no confirmation & no error within window | verify loop exhausts all tiers | `SUBMISSION_UNKNOWN` | HUMAN | HUMAN_REQUIRED after verify window; human confirms in ATS | HUMAN_REQUIRED |
| E12 | Confirmation page shown but no capturable id | success signal without evidence id | (still success if tier T1/T2 text present) | SYS | accept if "application received" + email tier; else SUBMISSION_UNKNOWN | VERIFIED / SUBMISSION_UNKNOWN |
| E13 | Duplicate submission attempt (already applied) | ATS "you already applied" / dedupe_key exists | `DUPLICATE` | SYS | mark VERIFIED if evidence of prior app, else SKIPPED | VERIFIED / SKIPPED |
| E14 | Per-application hard timeout exceeded | wall clock > cap | `OTHER` | SYS | if submit fired → SUBMISSION_UNKNOWN; else FAILED→RETRY_PENDING | SUBMISSION_UNKNOWN / RETRY_PENDING |

### F. Post-submit / verification
| # | Failure | Detection | Category | Owner | Recovery | End state |
|---|---|---|---|---|---|---|
| F1 | Confirmation email never arrives | mailbox poll timeout | `SUBMISSION_UNKNOWN` | HUMAN | try portal tier; then HUMAN_REQUIRED | HUMAN_REQUIRED |
| F2 | Portal "My Applications" doesn't show the req | authenticated re-check | `SUBMISSION_UNKNOWN` | HUMAN | re-check after delay; then HUMAN_REQUIRED | HUMAN_REQUIRED |
| F3 | Later rejection/withdrawal email | mailbox classifier | n/a | SYS | annotate ledger; does not change VERIFIED count | VERIFIED (annotated) |
| F4 | Verified but wrong resume/persona attached | artifact hash vs application | `OTHER` | HUMAN | flag for human; do not auto-resubmit | HUMAN_REQUIRED |

---

## 3. Recovery policy matrix

| Class | Auto-retry? | Max attempts | Backoff | Escalation |
|---|---|---|---|---|
| Transient network **pre-submit**, rate limit, LLM 5xx | yes | 3 | expo + jitter, honor Retry-After | RETRY_PENDING → next cycle → HUMAN after cap |
| Transient network **post-submit** | **no** | 0 | — | SUBMISSION_UNKNOWN → verify loop → HUMAN |
| Form-mapping / dropdown / upload | limited | 1–2 | immediate | HUMAN_REQUIRED |
| CAPTCHA / MFA / unknown legal Q / ATS changed | **no** | 0 | — | HUMAN_REQUIRED (+ snapshot; cool-down source) |
| Truth-validation failure | regenerate | 2 | — | HUMAN_REQUIRED |
| Account creation / email verify | 1 | 1 | — | HUMAN_REQUIRED |
| Stale / closed posting | no | 0 | — | CLOSED / SKIPPED |
| Duplicate | no | 0 | — | merge / SKIPPED / VERIFIED-if-prior-evidence |

**Global guardrails:** per-company cool-down after CAPTCHA/block; per-tenant serialization for
account-based ATSes; daily cap on account creations; circuit-breaker per source on `ATS_CHANGED`.

---

## 4. The "unknown submission state" protocol (most important)

```
submit() fires the POST
   ├── exception / timeout after POST ──────────► status = SUBMISSION_UNKNOWN
   ├── success page + capturable evidence ──────► status = SUBMITTED, enqueue verify
   ├── success page, no evidence id ────────────► status = SUBMITTED (weak), enqueue verify
   └── explicit error, no server-side create ───► status = FAILED (retry if pre-create & under cap)

verify worker (async, separate from apply worker), verification window e.g. 45 min:
   tier T1 confirmation id on page snapshot ....► VERIFIED
   tier T4 submit-response app/candidate id ....► VERIFIED
   tier T2 confirmation email matched ..........► VERIFIED
   tier T3 authenticated portal shows req ......► VERIFIED
   none within window .........................► HUMAN_REQUIRED (human checks the ATS, resolves to
                                                 VERIFIED or SKIPPED; system never re-submits)
```
Rules: SUBMISSION_UNKNOWN and SUBMITTED-unverified are **never** counted toward DAILY_TARGET. Only
`VERIFIED` counts. A row in SUBMISSION_UNKNOWN is **never** auto-transitioned to APPLYING/RETRY_PENDING.

---

## 5. Metrics that must exist (per day)

- discovered, deduped, filtered (by reason code), eligible, queued
- apply attempts, SUBMITTED, **VERIFIED** (the KPI), SUBMISSION_UNKNOWN, FAILED, HUMAN_REQUIRED
- per-ATS: attempt→verified rate, median time-to-submit, HUMAN_REQUIRED rate
- verify-loop: tier hit distribution, time-to-verify, unknown→human count
- human queue: opened, closed, median age, backlog
- integrity: truth-validation failures, unknown-legal-question hits, profile-incomplete blocks
- cost: LLM calls + spend by stage (see `LLM_COST_STRATEGY.md`)

Health rule of thumb: if `SUBMISSION_UNKNOWN + HUMAN_REQUIRED > 25%` of attempts on a mature adapter,
freeze that adapter and investigate.

---

## 6. Throughput math (why over-provision attempts)

Target: 100 VERIFIED/day. Assume, for the P1 adapters at maturity:
- eligible→queued yield after filters/dedupe: need ~2–3× eligible jobs vs target
- queued→submitted: ~80%
- submitted→verified: ~90%
- net attempt→verified: ~0.70–0.75

⇒ need ~135–160 apply attempts/day for 100 verified, drawn from ~180–260 eligible postings/day, which
(after ~60–75% filter/dedupe attrition) implies **~700–1200 raw postings/day** ⇒ **~800–1500 active
company boards** in the registry, refreshed on a 6–24h cadence. Registry size is the real throughput lever.

---

## 7. Adversarial test catalog (implemented in `tests/test_adversarial_*.py`)

| ID | Scenario | Expected |
|---|---|---|
| ADV-01 | "Senior Data Scientist" titled, JD says "early career" | SKIPPED `SENIORITY_TOO_HIGH` |
| ADV-02 | "US citizenship preferred" | ELIGIBLE (not filtered) |
| ADV-03 | "US citizenship is required" / "must be a US citizen" | SKIPPED `US_CITIZEN_ONLY` |
| ADV-04 | "We are unable to provide visa sponsorship" | SKIPPED `NO_VISA_SPONSORSHIP` |
| ADV-05 | "Visa sponsorship is available for this role" | ELIGIBLE |
| ADV-06 | "5+ years" only in Preferred section; Requirements say "0-2 years" | ELIGIBLE |
| ADV-07 | "Minimum 7 years of professional experience" in Requirements | SKIPPED `EXPERIENCE_REQUIREMENT_TOO_HIGH` |
| ADV-08 | "1-5 years of experience" | ELIGIBLE (range includes new grad) |
| ADV-09 | "trade secret" / "Victoria's Secret" in JD, no clearance | ELIGIBLE |
| ADV-10 | "Active TS/SCI clearance required" | SKIPPED `INCOMPATIBLE_SECURITY_CLEARANCE` |
| ADV-11 | Same req via Greenhouse + company mirror, apply URLs differ by `?gh_src=` | one application row |
| ADV-12 | Same req, two sources, different tracking URL | deduped |
| ADV-13 | JD edited post-discovery to add "10+ years required" | re-filter → SKIPPED |
| ADV-14 | LLM proposes bullet "Deployed on AWS" with no AWS fact | TRUTH_VALIDATION_FAILED → HUMAN_REQUIRED |
| ADV-15 | Resume omits graduation date | required-field check fails → HUMAN_REQUIRED |
| ADV-16 | Unknown sponsorship-phrased question on form | HUMAN_REQUIRED (never auto-answer) |
| ADV-17 | Submit clicked, confirmation never appears | SUBMISSION_UNKNOWN → HUMAN_REQUIRED, not counted |
| ADV-18 | Network timeout immediately after submit POST | SUBMISSION_UNKNOWN, no auto-retry |
| ADV-19 | `SUBMITTED`→`FAILED` transition attempted | InvalidTransitionError |
| ADV-20 | `SUBMISSION_UNKNOWN`→`APPLYING` transition attempted | InvalidTransitionError |
| ADV-21 | Non-US location ("London, UK") | SKIPPED `LOCATION_INELIGIBLE` |
| ADV-22 | Location unknown / blank | kept (`location_unknown`) |
| ADV-23 | Duplicate `dedupe_key` insert | second insert is a no-op, same row returned |
