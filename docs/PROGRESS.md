# Progress Report

Completed Phase 1 foundation:

- Created repository structure under `app/`, `config/`, `tests/`, `docs/`, `data/`, and `logs/`.
- Added configurable candidate profile, role taxonomy, company registry, and safety settings.
- Defined normalized job, company, and application models.
- Implemented explicit application state machine with `SUBMISSION_UNKNOWN` and terminal `VERIFIED` state.
- Added SQLite schema and repository operations for jobs, applications, and transition logging.
- Added `JobSource` and `ApplicationAdapter` interfaces.
- Added deterministic hard filters, deduplication helpers, persona mapping, truth validation, and structured logging.
- Added tests for state transitions, filters, deduplication, repository persistence, and resume truth validation.

Next engineering phase:

Completed additional foundation work:

- Added read-only Greenhouse, Lever, and Ashby discovery adapters.
- Added YAML-backed company registry loading.
- Added role taxonomy classification from `config/role_taxonomy.yaml`.
- Added incremental status detection for `NEW`, `UPDATED`, and `UNCHANGED` postings.
- Hardened deduplication with canonical URLs, requisition-like URL keys, normalized company/title/location keys, and description shingles.
- Hardened deterministic filters for sponsorship, citizenship-required phrasing, clearance context, preferred-only experience, and non-US location handling.
- Added deterministic truth-validation MVP for semantic bullets, required fields, provenance, and legal/authorization question routing.
- Added application queueing and daily KPI reporting.
- Added DB idempotency, foreign-key enforcement, WAL mode, and atomic status transitions.
- Promoted reviewer adversarial xfails into normal passing tests.
- Added candidate fact model loading and profile completeness gate.
- Added deterministic, ATS-friendly text resume artifact generation with validation and artifact hashing.
- Added explicit `docs/CODEX_PROGRESS.md` status tracking for Claude findings.
- Updated discovery to use explicit candidate sponsorship configuration and ATS/requisition-derived application dedupe keys.
- Added ATS-agnostic form field classification/resolution for common fields and legal fail-closed handling.
- Added `human_tasks` schema and idempotent task creation.
- Added SmartRecruiters and Workday read-only discovery adapters against source-contract fixtures.
- Expanded hard-filter coverage for Round 1.5 sponsorship, experience, ITAR/export-control, and posted-date contracts.
- Full test suite is now clean with no expected-failure markers: `140 passed`.

Next engineering phase:

Add artifact cache reuse by persona/skill signature, then add non-submitting ATS form inspection/canary tests before any real application adapter is allowed to submit.
