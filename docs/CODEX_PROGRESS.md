# Codex Progress

## Current Status

Codex remains the primary implementation owner. Claude Round 1 P0/P1 findings have been treated as blocking before continuing later phases.

Latest local verification:

- `python3 -m pytest -q`
- Result: `464 passed, 1 skipped, 2 xfailed`

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
- Shared DOM-driven dry-run adapter foundation with Greenhouse, Lever, and Ashby wrappers against realistic fixture HTML; they stop before submit even when `would_submit=true`.
- PDF upload gate coverage proving invalid resume validation blocks the resume field before submit-ready state.
- Optional Greenhouse live dry-run runner that performs read-only Playwright navigation, refuses `real_submission_enabled=True`, and hands the page to the no-submit dry-run adapter.
- Approval-gated autofill preview builder and CLI rendering; it rejects unapproved, mutated-hash, and not-submit-ready transcripts.
- Dry-run application worker integration that atomically claims READY work, fences stale leases before browser access, persists DOM transcripts, returns no-submit work to READY, and refuses real-submission mode.
- First live Greenhouse DOM dry-run completed against Anthropic's public application page: 24 fields discovered, 3 safe fields filled, 14 human-required, `would_submit=false`, upload calls `0`, submit invocations `0`; audit report is in `docs/greenhouse_live_dry_run_report.json`.
- Phase 4.2 safety closure: ordinary HTTP 4xx responses are no longer retried; live autofill requires explicit human invocation and performs a post-fill hard-stop scan; the live evidence bundle remains no-submit and candidate-profile TODO values remain HUMAN_REQUIRED.
- Phase 4.3 Gate G evidence bundle: `scripts/live_dry_run.py` reproducibly archives live DOM, sanitized screenshots, DOM-traceable field map, browser actions, safety differential, and immutable transcript; the committed Anthropic run has zero submit invocations.
- Round 3.4 follow-up: committed evidence bundles no longer include SQLite databases; form-region screenshots and sanitized transcript/HTML artifacts are generated by the reproducible script; shared hidden-field defenses cover disabled, opacity, and offscreen decoys; reusable live runner now requires lease metadata and an approved transcript before autofill.
- Shared ATS red-team hardening: Lever/Ashby nested labels and radio groups now resolve without glyph bleed; live autofill requires worker lease identity and performs per-field lease checks.
- Added `docs/REAL_CANDIDATE_PROFILE_BLOCKERS.md` so missing real facts are explicit and do not block unrelated engineering work or invite fabricated values.
- Added a shared legal-question matrix for Greenhouse/Lever/Ashby that keeps authorization, sponsorship, citizenship, clearance, salary, relocation, and unmappable legal selects fail-closed.
- Generalized the no-submit live evidence runner to accept Greenhouse, Lever, and Ashby adapters through one shared `--ats` path. Public Lever and Ashby navigation was exercised with real Chromium on 2026-09-07; both captured live DOM and stopped on provider CAPTCHA/hard-stop before transcript creation, with zero submit invocations and no challenge bypass.
- Candidate profiles with `meta.candidate_id: TODO` now receive a stable internal UUID namespace. This identifier is database-only and does not unlock or fabricate candidate facts.
- Candidate confirmed their name as the canonical identity for the supplied resume and LinkedIn profile; the decision is recorded without changing the no-submit boundary.
- Completed the authorized open-source reference comparison for CareerWeaver, applyai, and ai-job-agent. Their MIT licenses, exact review commits/files, local treatment, and safety conflicts are recorded in `THIRD_PARTY_NOTICES.md` and `docs/OPEN_SOURCE_REFERENCE_COMPARISON.md`. Useful patterns were cleanly reimplemented; no upstream source was copied.

## Next

1. Repeat Greenhouse live dry-runs with a completed, validated candidate profile and real PDF QA artifact, still without submitting.
2. Keep application concurrency at one until multiple reviewed Greenhouse dry-run transcripts are complete.
3. Add provider-backed LLM tailoring only after deterministic prompt contracts and evals are in place.

## OpenAI Provider Checkpoint (2026-09-07)

- Added a minimal OpenAI Responses API provider using environment-only credentials, `store: false`,
  bounded output, timeout handling, and no blind POST retry.
- Added API-reported token accounting, configurable model prices, conservative unknown-model costing,
  identical-request in-process caching, and cheap-stage model-tier enforcement.
- Added a fail-closed runtime factory and a no-cost `--llm-status` command. AI and candidate PII transfer
  remain disabled in the tracked settings.
- Converted Claude's model-tier xfail into a passing adversarial test.
- Full suite after provider boundary: 519 passed, 1 skipped, 13 xfailed.
- Added date-keyed SQLite budget reservations so concurrent workers and restarted processes share the
  same daily cap without persisting prompts or responses. Converted the corresponding Claude xfail.
- Full suite after persistent budget accounting: 522 passed, 1 skipped, 12 xfailed.
- Deferred at that checkpoint: durable cross-process response cache, structured prompt/eval contracts,
  and provider-backed tailoring. No live paid API request was made.

## Selection-Only Tailoring Checkpoint (2026-09-07)

- Added a strict JSON fact-selection contract and connected it to `ApplicationPreparer` when the LLM
  runtime is explicitly enabled.
- The low-cost `gpt-5-nano` selector can only return allowlisted fact IDs. Resume wording continues to
  come from the local deterministic profile facts.
- Identity, contact, address, authorization/legal, missing, and literal-only facts are excluded from
  provider prompts. Invalid JSON, extra keys, fabricated IDs, and provider uncertainty all fail back
  to deterministic selection.
- Resume audit metadata records token usage, model, cost, cache status, and fallback reason without
  storing prompts or candidate PII.
- Full suite: 528 passed, 1 skipped, 12 xfailed.

## Resume Structure And Filter Reconciliation (2026-09-07)

- Added typed Skills, Projects, and Experience sections to deterministic resume artifacts while
  preserving verbatim candidate facts and the compatibility/provenance fact list.
- Contact and profile links render only in the header; identity, contact, education, and legal facts
  cannot leak into the generic resume bullet sections.
- Converted Claude's missing resume-section xfail into a passing test.
- Fixed U.S. state abbreviation matching so `ga` inside `Singapore` cannot make an overseas role appear
  U.S.-eligible. Explicit foreign locations also override a generic `Remote` marker.
- Discovery now reruns hard filters for unchanged postings and moves only unstarted `ELIGIBLE/QUEUED`
  applications to `SKIPPED` when rules make them ineligible. Concurrent state changes are not overwritten.
- A read-only OpenAI rediscovery processed 779 postings with zero errors and reconciled all Singapore
  `ELIGIBLE/QUEUED/READY` rows to zero. No form filling or submission occurred.
- The supplied resume was parsed into additional local candidate facts for PDF QA. Those facts and the
  generated artifacts remain gitignored and were not committed.
- Full suite: 535 passed, 1 skipped, 12 xfailed.

## Claude Follow-Up Safety Closure (2026-09-07)

- P1 fixed: `llm.send_candidate_pii=false` now prevents the provider router from being built. The
  dashboard/status field is an enforced runtime boundary rather than a display-only claim.
- P1 fixed: live evidence leases now default to a ten-minute TTL and reject values below one minute.
- P1 fixed: `--approved-by` requires an exact `--confirm-apply-url` acknowledgment, and the final
  browser URL is checked again before any autofill.
- P2 fixed: unknown models cannot use a caller-declared zero cost; conservative configured prices are
  applied. Four related Claude xfails were converted to passing tests.
- P3 fixed: actual provider cost above a reservation is committed to the ledger before the router fails
  closed, so an overrun is never omitted from accounting.
- P3 resolved: the evidence role is parsed from the live Greenhouse page title instead of trusting a
  stale CLI label.
- P3 rejected as inapplicable: the current OpenAI Responses API create schema does not expose `seed`.
  Reproducibility uses a fixed model, strict ID-only output contract, request hash cache, and local
  deterministic resume rendering.
- Evidence payload sanitization now redacts every populated candidate field value, including names,
  addresses, profile URLs, and custom free text.
- A synthetic TEST_ONLY Greenhouse v5 run captured 25 real DOM fields with a complete field map and
  transcript, no lease loss, no autofill, no upload, and zero submit invocations. This is a technical
  capture checkpoint, not an approved Gate G pass.
- Full suite: 543 passed, 1 skipped, 8 xfailed.

## Multi-Company Discovery Precision (2026-09-07)

- Root cause of the inflated OpenAI match count was confirmed: 368 of 369 active candidates were
  `job_family=UNKNOWN`, including legal, hardware, research, and senior roles. UNKNOWN jobs now remain
  discoverable for later classification but cannot become application-eligible.
- Added verified read-only Greenhouse boards for Anthropic, Stripe, and Databricks. Google, Meta,
  Apple, and Tesla remain registered but inactive until dedicated official-careers adapters exist.
- Added clear required `3+ years` filtering while preserving ranges that include early-career
  candidates and explicitly preferred experience. Manager titles are now excluded for the new-grad
  profile.
- Expanded non-U.S. location handling for common locations observed in the live boards.
- Fixed Greenhouse `/jobs/search?gh_jid=...` dedupe: the generic path word `search` can no longer act as
  a requisition ID. Placeholder metadata such as `See Opening ID` is also rejected.
- Discovery now idempotently creates a missing application for an unchanged eligible job, allowing
  recovery after a previous dedupe defect. Legacy databases also check `job_id` transactionally before
  inserting an application.
- Live read-only results: OpenAI 750 jobs, Anthropic 584, Stripe 582, and Databricks 776. After strict
  filtering, six active candidates remain: one OpenAI role and five Stripe roles. No application form
  was opened and no submission occurred.

## Open-Source Reference Review

### Fixed / Adapted

- Adopted the compatible concepts of preflight gating, durable evidence traces, field read-back verification, ATS-specific normalization, and operator-visible status history. These are implemented through the existing local safety architecture rather than copied from upstream.
- Added a regression test ensuring the comparison and provenance records continue to state the no-copy and no-submit policy.

### Deferred

- No direct upstream browser automation was imported. Provider-specific live behavior remains deferred behind the existing no-submit, approval, lease, and HUMAN_REQUIRED gates.

### Rejected

- Direct auto-submit and weaker “success” assumptions from reference implementations were rejected because they conflict with submission verification, `SUBMISSION_UNKNOWN`, transcript/hash approval, and `real_submission_enabled=false` invariants.
## 2026-09-07 Live batch review correctness hardening

- Fixed Playwright live-field labels leaking entire Greenhouse form-region text into every field. Labels now prefer exact `for`/ARIA associations and reject oversized ancestor text.
- Prevented non-text controls such as location comboboxes from entering the LLM essay path.
- Prevented the resume artifact from being reused for cover-letter or other upload fields.
- Normalized punctuation in standard-answer matching, preferred city-specific answers for city autocomplete widgets, and kept unknown education attendance dates unresolved.
- Added fail-closed behavior for missing/unstable selectors, unmatched options, and unconfirmed autocomplete values. Unready batch records are rejected by both the dashboard endpoint and the headed fill script.
- Fixed missing screenshot rendering and disabled the batch fill action for blocked/unready records.
- Verified the current Scale AI Greenhouse DOM without submission. All supported widgets now fill; the record remains correctly blocked only on the candidate's unknown education start year.
- Safety state remained unchanged: no submit path was added and no application was submitted.

## 2026-09-07 Notion Ashby form-load repair

- Fixed batch form readiness detection for React ATS pages that render controls without a traditional `<form>` wrapper.
- Fixed Ashby evidence-directory collisions caused by every application URL ending in `/application`; slugs now use the requisition UUID.
- Added exact-application selection to the diagnostic batch command.
- Added a separate official-site link to the review UI, while keeping agent-assisted fill disabled for blocked or unresolved records.
- Re-captured Notion's live Ashby DOM without submission. The form loads correctly; the AI Early Career record is now `attention` only because one required AI-technologies answer needs candidate review.

## 2026-09-07 Field-coverage audit

- Replaced the misleading raw auto-fill count in batch review with required-field and total-field coverage percentages.
- Fixed Ashby radio/checkbox extraction so option labels no longer masquerade as separate questions, and required styling is recognized as required state.
- Routed AI tool/technology experience prompts through the verified-facts drafting path.
- Live Benchling result: 6/8 required fields are safely resolved (75%). The remaining privacy acknowledgement and nuanced work-authorization category require explicit candidate choices; after those two choices the form can reach 100% required coverage.
- The 90% target is treated as a coverage objective, never as permission to infer legal status or consent.

## 2026-09-08 Hash-bound batch answer review

- Added dashboard controls for required candidate-only answers, including real DOM option lists.
- Human approvals are bound to the exact application URL and canonical SHA-256 of `record.json`; any refreshed form invalidates stale approval.
- Missing answers, unknown field IDs, values outside the captured option set, blocked records, and preparation fill failures all fail closed.
- Approved answers are merged into the headed browser fill only after server-side revalidation. The browser helper still exposes no submit operation.
- Coverage now counts approved answers only while their approval artifact remains valid, allowing truthful 100% required coverage without guessing consent, relocation, or legal status.
- The approver name is remembered only in browser-local storage and is not hard-coded or committed as candidate PII.

## 2026-09-08 Anthropic compatibility repair

- Invalidated and re-captured the Anthropic batch record after screenshots exposed identity values in unrelated fields.
- Added a second semantic boundary around profile facts: identity/contact values now require narrow label classes even if a future scanner emits polluted text.
- Added regression coverage proving name facts cannot enter motivation, additional-information, or LinkedIn fields.
- Harvested current Greenhouse React-select options for human-only questions and bound them to the approval artifact.
- Changed headed assisted fill to close immediately on any mapped-field interaction failure instead of leaving a partially filled form available for submission.
- Live Anthropic differential now shows no identity contamination. Motivation contains a verified-facts draft, Additional Information is empty, LinkedIn contains the configured URL, and the remaining four required controls are explicit AI-policy/interview/arbitration acknowledgements.
- Re-navigation now rebinds reviewed values by normalized label and input kind instead of trusting ephemeral ATS selectors. Any required-field drift or ambiguous match closes the browser before filling.
- Removed the duplicate resume-upload fallback that could target non-resume file controls.
- Live rebind verification found and safely replaced four changed selectors on both Notion and Benchling; Anthropic retained a 26-field stable structure.
- Batch records now carry an explicit schema version. Older captures are surfaced as `STALE_REVIEW_RECORD` and cannot be approved or filled, preventing fixed code from consuming screenshots/transcripts produced by obsolete mapping logic.
- Rebuilt the Anthropic, Benchling, Notion, and Scale AI baseline records with schema v2 against their current live forms; all remained non-submitting attention records for explicit candidate-only answers.

## 2026-09-08 Browser fill read-back verification

- Closed a batch-testing blind spot where a Playwright fill/click that returned successfully was counted as a successful fill without checking the final DOM state.
- Added fail-closed read-back verification for text inputs, native selects, React comboboxes, radio/checkbox groups, question-scoped controls, and file uploads.
- Both headless batch preparation and the final headed assisted-fill path now stop on a missing selector, empty value, wrong selected option, discarded React value, or other transcript/browser mismatch.
- Added browser-level regression tests, including the observed failure class where an essay field is expected but the DOM contains the candidate name instead.
- A real Anthropic Greenhouse run exposed and closed three verifier defects: long essays being probed as paths, React-select values being read from the input wrapper instead of the control, and file inputs unmounting immediately after a successful upload.
- Optional Greenhouse phone-country selection is no longer claimed as verified because its final DOM retains only a non-unique dialing code (`+1` for the configured United States answer).
- The repeated Anthropic live run verified every attempted safe fill. Its only remaining blockers are four explicit candidate decisions: AI-use policy, prior interview history, reading the arbitration agreement, and agreement to arbitrate.
- Verification: `687 passed, 1 skipped`; Python bytecode compilation and `git diff --check` passed. Ruff was not installed in the execution environment.
- Safety state remains unchanged: `real_submission_enabled=false`; no submit primitive was introduced and no application was submitted.

## 2026-09-08 Cross-ATS live read-back audit

- Re-ran current public application DOMs for Anthropic and Scale AI (Greenhouse), plus Benchling and Notion (Ashby), using the real candidate profile and validated resume without submitting.
- Anthropic: every attempted safe field passed browser read-back; only AI-use policy, prior interview history, and two arbitration acknowledgements remain candidate-only.
- Benchling: resume, profile, pronouns, hybrid-work answer, verified-facts AI-tools draft, EEO choices, and sponsorship passed read-back. Privacy-policy consent and its nuanced work-authorization category remain candidate-only.
- Notion: all attempted safe fields passed read-back. Relocation destinations and the specific `OPT/H1B/TN/None/Other` sponsorship category remain candidate-only because the current profile does not establish those facts.
- Scale AI: closed required phone-country verification by retaining the exact React option clicked and requiring a non-empty post-click control state. The only remaining blocker is the candidate's education start year; job-availability dates remain prohibited from filling that field.
- Added adversarial tests proving secondary React option evidence cannot make an empty control pass verification.
- Verification: `689 passed, 1 skipped`; bytecode compilation and `git diff --check` passed. No application was submitted.

## 2026-09-08 Candidate-approved recurring answers

- Recorded the candidate-provided education, authorization, relocation, and ATS-specific answers in gitignored local configuration only; concrete personal values are not repeated in tracked documentation.
- Added company-and-full-prompt-bound `approved_exact` answers for Anthropic AI/interview/arbitration questions, Benchling privacy/work-authorization questions, and Notion relocation/sponsorship questions. Similar wording at another company does not match.
- Added all-or-nothing multi-option mapping so comma-bearing choices such as `New York, NY` remain intact and every requested checkbox must exist in the current DOM.
- Added profile-derived education start month/year handling without allowing the generic job-availability answer to enter education rows.
- Re-ran all four live forms without submission. Required-field browser-verified coverage is Anthropic 13/13, Benchling 8/8, Notion 14/14, and Scale AI 10/10; all four review records are `READY` with zero blockers.
- Verification: `692 passed, 1 skipped`; bytecode compilation, PII guard, and `git diff --check` passed. `real_submission_enabled=false` remains unchanged.
