# Codex Progress

## Current Status

Codex remains the primary implementation owner. Claude Round 1 P0/P1 findings have been treated as blocking before continuing later phases.

Latest local verification:

- `python3 -m pytest -q`
- Result: `316 passed, 1 skipped`

## Claude Round 1 Findings

### Fixed

- P0-1: Added explicit `SUBMISSION_UNKNOWN` and `VERIFIED` statuses. `VERIFIED` is the only success state counted by daily KPI reporting. `SUBMISSION_UNKNOWN` cannot transition back to `APPLYING` or `RETRY_PENDING`.
- P0-2: Added database-level application idempotency with `dedupe_key TEXT UNIQUE`; pipeline-generated application keys use `candidate_id | company_id | ATS/requisition_key`.
- P0-3: Added sponsorship/work-authorization filtering. Discovery now passes explicit candidate sponsorship configuration from `config/candidate_profile.yaml`; unknown work-authorization profile data routes no-sponsorship cases to `HUMAN_REQUIRED`.
- P0-4: Enabled SQLite foreign keys, WAL mode, and busy timeout on every repository connection.
- P1-1: Reworked experience parsing to avoid rejecting ranges that include new grads and to ignore preferred-only high-experience language.
- P1-2: Reworked clearance detection to require clearance/security context instead of matching bare "secret".
- P1-3: Hardened cross-source deduplication with canonical URL stripping, requisition-like URL keys, normalized company/title/location keys, and description shingles.
- P1-4: Made state transitions atomic with `BEGIN IMMEDIATE`, compare-and-swap update, and rowcount validation.
- P1-5: Replaced exact-string-only truth validation with deterministic semantic support checks, required-field checks, legal-question routing, and provenance validation.
- P1-6: Added candidate fact IDs, literal-only authorization facts, and `profile_completeness_gate()`.
- P1-7: Added conservative US/remote location handling and clearly non-US skip behavior.
- P1-8: Added `SUBMISSION_UNKNOWN -> VERIFIED` for async evidence discovery.
- P1-9: Added posted-date parsing for Greenhouse `updated_at`, Lever `createdAt`, and Ashby `publishedAt`.
- P1-9a: Expanded experience range parsing for en dash, em dash, spaced hyphen, and `to` separators.
- P1-10: Expanded no-sponsorship detection for additional common phrasings.
- P1-11: Added ITAR/export-control/U.S. Person filtering.
- P1-12: Added deterministic overreach and unsupported-number guards to provenance validation.
- P2-1: Broadened `upsert_job` so mutable columns are refreshed on rediscovery.
- P2-2: Removed `UNIQUE(apply_url)` from the fresh schema and added a legacy-DB fallback for old apply-url uniqueness conflicts.
- P2-3: Added `human_tasks`, `insert_resume_artifact()`, and `attach_resume_to_application()`.
- P2-4: Added missing failure categories from the failure model.
- P2-5: Added YAML taxonomy title classification and changed deterministic filtering so `UNKNOWN` family is kept for later review instead of dropped.
- P2-6: Normalized adapters to pass visible text into `Job`, so description hashes are not based on raw HTML markup for supported sources.
- Round 2 source contracts: Added read-only SmartRecruiters and Workday source adapters against fixtures.

### Deferred

- Workday application automation and iCIMS/Taleo discovery/application adapters remain deferred until no-account ATS discovery and verification are stable.
- Browser automation and live submission remain deferred; `real_submission_enabled` is still `false`.
- LLM-based extraction, tailoring, and entailment judging remain deferred behind deterministic gates and cost controls.

### Rejected

- None. All P0/P1 Claude findings were accepted and implemented.

## Claude Round 2 / 2.5 Findings

### Fixed

- P1-13: `ApplicationWorkflowRunner` now treats the database row as source of truth when a repository is supplied, refuses non-runnable states, persists transitions, increments `attempt_count`, sets `applied_at`, and separates pre-submit `FAILED` from post-submit `SUBMISSION_UNKNOWN`.
- P1-14: Discovery no longer performs unsafe application check-then-act. It uses conflict-safe application insert by requisition-derived dedupe key and transitions only the winning insert.
- P1-15: Numeric resume provenance now supports exact integers, percentages, currency-like values, decimals, `k` shorthand, `15+`-style facts, years/dates, and matching ranges such as `1-3` / `1–3`; unsupported numbers fail closed.
- P1-16/P1-17: Sponsorship and citizenship filtering now uses explicit hard-negative rules plus a negation-window sponsorship detector while preserving ambiguous/positive sponsorship language.
- Profile gate: Required `TODO` facts block preparation/submission regardless of `real_submission_enabled`.
- Verification API: Application adapters may return structured `VerificationEvidence`; T1-T4 evidence can promote to `VERIFIED`, while weak evidence is stored without counting as success.
- HTTP safety: Shared HTTP client now applies timeouts, bounded retries, `Retry-After`, jittered backoff, per-host rate limiting, and a user agent.
- DB/worker safety: Added queue/status indexes, idempotent `human_tasks`, `worker_id`, `claimed_at`, `lease_expires_at`, `lease_epoch`, transactional worker claim, lease fencing helpers, and dry-run transcript persistence.
- P1-19: `mark_human_required()` now synthesizes a minimal human task when callers omit one, so `HUMAN_REQUIRED` rows remain visible to the operator queue.
- P1-20: Application dedupe no longer varies with source labels when a canonical URL/requisition identity is available.

### Deferred

- Live Playwright form automation for Greenhouse/Lever/Ashby remains deferred behind dry-run/preview and human-review gates.
- Real submission remains disabled; `real_submission_enabled` is still `false`.
- Provider-backed LLM tailoring remains deferred. The current tailoring planner is deterministic and fact/provenance gated until provider configuration and evals are added.
- Workday application automation and iCIMS/Taleo adapters remain deferred until the Greenhouse/Lever/Ashby no-submit pipeline is stable.

### Rejected

- None. The blocking/high-priority Round 2 findings were accepted. Items not implemented yet are deferred for safety, not rejected.

## Implemented Since Phase 1

- Read-only Greenhouse, Lever, and Ashby discovery adapters.
- YAML company registry loading.
- YAML role taxonomy classification.
- Incremental discovery status detection.
- Application queueing.
- Daily KPI reporting with timezone-aware daily counts.
- Deterministic resume artifact generation, validation, and hashing.
- `--check-profile`, `--discover`, `--queue-eligible`, and `--daily-report` CLI commands.
- ATS-agnostic form field taxonomy resolver with fail-closed handling for legal/authorization fields.
- Human task schema and idempotent task creation for application/category blocking cases.
- Read-only SmartRecruiters and Workday fixture-backed source contracts.
- Verification evidence-tier persistence with T1-T4 strong evidence promotion and T5 weak-evidence storage.
- Deterministic PDF resume generation with structured JSON intermediates and stable artifact hashes.
- JD-aware FAST/DEEP tailoring planner constrained to candidate fact IDs.
- `ApplicationPreparer` for QUEUED -> TAILORING -> READY with preview output.
- Dry-run transcript model/table for non-submitting form/application payload review.
- Worker lease claim/fencing primitives for future concurrent application workers.
- Canonical form dry-run engine that resolves extracted ATS fields, writes transcripts, and opens human tasks for unresolved required fields.
- `--dry-run-next` CLI command for READY applications with validated resume artifacts.
- HTML form field extractor for Greenhouse/Lever/Ashby-style DOM snapshots, with a provider bridge into the dry-run engine.
- Browser page capture abstraction that reads HTML/screenshots, detects CAPTCHA/MFA, and refuses field extraction when a human challenge is present.
- Worker lease reaper that routes expired pre-submit work to `RETRY_PENDING` and expired post-submit work to `SUBMISSION_UNKNOWN`.
- Dedicated `submit_attempted_at` marker so reaping never depends on free-text notes.
- PDF QA gate plus paginated, non-truncating, ASCII-safe PDF rendering.
- Dry-run transcript approval/hash helpers and persona/requisition payload fields.
- Multi-category dry-run human tasks for unresolved form blockers.
- Radio group coalescing, custom-question label fallback, stricter legal form routing, select-option validation, and single-token-name blocking.
- HTTP client tests for per-host throttling, bounded retries, Retry-After seconds/HTTP-date, 5xx/429 behavior, timeouts, and no blind POST retry.
- Browser hard-stop state wiring for CAPTCHA/MFA/email-verification tasks.
- Greenhouse DOM-driven dry-run adapter against realistic fixture HTML; it stops before submit even when `would_submit=true`.
- PDF upload gate coverage proving invalid resume validation blocks the resume field before submit-ready state.
- Optional Greenhouse live dry-run runner that performs read-only Playwright navigation, refuses `real_submission_enabled=True`, and hands the page to the no-submit dry-run adapter.

## Next

1. Exercise Greenhouse live dry-run navigation against reviewed public postings without submitting.
2. Reuse the DOM dry-run adapter pattern for Lever and Ashby.
3. Add approval-gated autofill previews backed by persisted dry-run transcripts.
4. Add live worker integration tests before raising application concurrency cautiously.
5. Add provider-backed LLM tailoring only after deterministic prompt contracts and evals are in place.
