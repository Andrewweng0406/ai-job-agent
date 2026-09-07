# Architecture

This repository implements the Phase 1-4 safety foundation: read-only discovery, normalization, hard filtering, safe queueing, deterministic tailoring, ATS-friendly PDF resume artifacts, dry-run application preparation, verification evidence persistence, and daily reporting. It intentionally does not perform live application submission.

The system is organized around deterministic, auditable pipeline stages:

1. Job sources discover and normalize raw jobs behind `JobSource`.
2. Normalization computes canonical identifiers and description hashes.
3. Deduplication prevents previously seen jobs or applications from entering the queue.
4. Hard filters remove roles with clear disqualifiers before any LLM work.
5. Persona classification maps accepted job families to resume personas.
6. Tailoring selects only candidate fact IDs from `config/candidate_profile.yaml`.
7. Resume generation writes a structured JSON intermediate and an ATS-friendly PDF artifact.
8. Application preparation moves queued rows through `TAILORING -> READY` and emits a preview.
9. Browser/application work must run as persisted dry-run transcripts before any submit path is considered.
10. Application adapters prepare, fill, submit, and verify supported ATS workflows behind hard safety gates.
11. SQLite stores jobs, applications, worker leases, state transitions, resumes, dry-run transcripts, human tasks, and confirmation evidence.
12. Daily reporting converts stored UTC timestamps into the configured local timezone before counting daily KPIs.

Safety decisions:

- Real submission is disabled by default in `config/settings.yaml`.
- CAPTCHA, MFA, legal certification, ambiguous questions, and unsupported workflows must become `HUMAN_REQUIRED`.
- A submission counts only after `verify_submission()` returns reliable success evidence.
- `SUBMISSION_UNKNOWN` is distinct from `SUBMITTED` and cannot automatically retry into `APPLYING`.
- Candidate facts marked `TODO` are treated as missing and must not be guessed.
- Resume generation refuses to produce an artifact while required profile facts are missing.
- Worker claims are transactional and fenced by `worker_id` plus `lease_epoch`.
- Discovery application creation is conflict-safe by requisition-derived dedupe key.
- Dry-run transcripts are immutable payload snapshots; approval and real submission are separate steps.
