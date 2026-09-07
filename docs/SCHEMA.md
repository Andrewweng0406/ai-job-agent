# Database Schema

The initial SQLite schema is defined in `app/database/schema.py`.

Core tables:

- `companies`: employer registry and ATS metadata.
- `jobs`: normalized job records with uniqueness on source requisition ID and apply URL.
- `applications`: one application tracking record per queued job.
- `application_state_transitions`: append-only status transition log.
- `job_filter_results`: append-only hard-filter decisions and skip reasons.
- `resumes`: generated resume artifacts associated with exact jobs.
- `human_tasks`: idempotent human-required work items with context needed to resume safely.

The schema preserves historical applications and records the exact status, resume ID, failure category, human-required reason, submission confirmation data, and generated resume artifact hash.
