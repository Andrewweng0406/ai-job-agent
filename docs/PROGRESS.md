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

Next engineering phase:

Implement resume artifact generation from the fact model, then add non-submitting ATS form inspection/canary tests before any real application adapter is allowed to submit.
