# Codex Progress

## Current Status

Codex remains the primary implementation owner. Claude Round 1 P0/P1 findings have been treated as blocking before continuing later phases.

Latest local verification:

- `python3 -m pytest -q`
- Result: `140 passed`

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

## Next

1. Add artifact cache reuse by persona/skill/profile signature.
2. Add verification worker evidence-tier persistence.
3. Add seeded company registry entries for read-only discovery testing.
4. Add non-submitting ATS form inspection/canary tests.
