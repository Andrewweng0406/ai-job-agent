# Architecture

This repository currently implements Phase 1 foundation only. It intentionally does not perform live application submission.

The system is organized around deterministic, auditable pipeline stages:

1. Job sources discover and normalize raw jobs behind `JobSource`.
2. Normalization computes canonical identifiers and description hashes.
3. Deduplication prevents previously seen jobs or applications from entering the queue.
4. Hard filters remove roles with clear disqualifiers before any LLM work.
5. Persona classification maps accepted job families to resume personas.
6. Resume generation will use only facts from `config/candidate_profile.yaml`.
7. Application adapters prepare, fill, submit, and verify supported ATS workflows.
8. SQLite stores jobs, applications, state transitions, resumes, and confirmation evidence.

Safety decisions:

- Real submission is disabled by default in `config/settings.yaml`.
- CAPTCHA, MFA, legal certification, ambiguous questions, and unsupported workflows must become `HUMAN_REQUIRED`.
- A submission counts only after `verify_submission()` returns reliable success evidence.
- Candidate facts marked `TODO` are treated as missing and must not be guessed.

