# Open-Source Reference Comparison

Reviewed on 2026-09-07 against the following MIT-licensed repositories and
their recorded commits:

| Reference | Useful patterns | Local decision |
|---|---|---|
| [CareerWeaver](https://github.com/idea-torx/CareerWeaver) | Preflight before browser work, durable JSONL traces, explicit `held`/`audit_pending` states, field read-back verification, and real-Chrome routing for bot-walled providers. | Conceptually reimplemented where compatible. The local pipeline already has preflight gates, evidence bundles, browser differential checks, lease fencing, and a hard no-submit boundary. No source copied. |
| [applyai](https://github.com/muhammad-saadd/applyai) | ATS-specific Greenhouse/Lever/Ashby label and selector fallbacks, job-description extraction, and normalized form-field records. | Used as a coverage checklist for the shared extractor. Local hidden-field filtering, legal-question routing, provenance validation, and approval/hash checks are stricter. No source copied. |
| [ai-job-agent](https://github.com/AkbarDevop/ai-job-agent) | Human-readable application tracker status updates, resume parsing separated from tracking, and provider-specific adapters. | The local application ledger, status history, artifact hashes, and provider adapters cover these concerns with stronger database idempotency and verification semantics. No source copied. |

## Safety Comparison

The references are engineering references, not behavioral authorities. Their
browser/application flows include direct automation paths that are not safe to
adopt here. This project keeps `real_submission_enabled=false`; a browser run
may capture, normalize, verify, and produce an approval-gated autofill preview,
but it does not submit. Ambiguous legal questions, hidden or honeypot fields,
missing candidate facts, CAPTCHA/MFA, stale leases, transcript hash changes,
and unconfirmed submission outcomes remain HUMAN_REQUIRED or
SUBMISSION_UNKNOWN according to the local state machine.

The useful upstream ideas were therefore cleanly reimplemented rather than
copied: provider-aware extraction is shared, evidence is immutable and
sanitized, and operator-visible status changes are persisted in the local
ledger. No upstream source file was incorporated.

## Regression Coverage

Existing tests cover the adapted behavior: pre-submit hard stops, hidden-field
and nested-label extraction, cross-ATS normalization, upload/read-back
verification, lease fencing, approval/hash validation, submission uncertainty,
and database idempotency. The reference governance test also verifies that
this comparison and the provenance record remain present.
