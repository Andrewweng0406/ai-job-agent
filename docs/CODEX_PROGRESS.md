# Codex Progress

## Current Status

Codex remains the primary implementation owner. Claude Round 1 P0/P1 findings have been treated as blocking before continuing later phases.

Latest local verification:

- `python3 -m pytest -q`
- Result: `59 passed`

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

### Deferred

- P2-1: Full mutable-column refresh on `upsert_job` should be broadened before high-volume discovery.
- P2-2: `jobs.apply_url` uniqueness should be revisited for ATSes that reuse a generic application URL.
- Workday/iCIMS/Taleo discovery and application adapters remain deferred until Greenhouse/Lever/Ashby read-only discovery is stable.
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

## Next

1. Broaden `upsert_job` update behavior and handle shared apply URLs safely.
2. Add artifact cache reuse by persona/skill/profile signature.
3. Add seeded company registry entries for read-only discovery testing.
4. Add non-submitting ATS form inspection/canary tests.

