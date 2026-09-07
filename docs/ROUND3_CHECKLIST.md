# ROUND3_CHECKLIST.md — Phase 4 Implementation Review Checkpoint

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Rule:** do not trust `CODEX_PROGRESS.md`. Inspect code, run the named test, try to break it. Mark
**PASS** only when demonstrated. `real_submission_enabled` stays `false`.

Round 3 goal: prove Phase 4 can do **REAL JOB → TRUTHFUL TAILORED RÉSUMÉ → ATS-FRIENDLY PDF →
APPLICATION FORM → DRY RUN → HUMAN REVIEW** with no accidental submission, no duplicate submission, no
fabricated résumé content, and no hidden unresolved questions.

---

## Status snapshot (last reviewed at `6bbe19c` + uncommitted form-engine/dry-run WIP)

| Area | State | Notes |
|---|---|---|
| Worker lease + **reaper (P1-18)** | **PASS** | `reap_expired_leases()`: `APPLYING`+`SUBMIT_POST_SENT` → `SUBMISSION_UNKNOWN`, else `APPLYING`/`TAILORING` → `RETRY_PENDING`; CAS + transaction + logged. `tests/test_worker_lease.py`. Caveat P1-24 below. |
| Form engine — legal question routing (P1-22) | **PASS** | Only a tight `sponsorship` Y/N pattern auto-answers; every other legal/work-auth/citizenship label → `HUMAN_REQUIRED`. `tests/test_form_engine_redteam.py`. |
| Form engine — SELECT option mapping (P1-23) | **PASS (in-round)** | Resolved value checked against `field.options`; unmappable → `HUMAN_REQUIRED`/`FORM_MAPPING`. `tests/test_form_engine_redteam.py::test_select_value_not_in_options_is_form_mapping_human_required`. |
| Dry-run — no submit | **PASS** | `FormDryRunEngine.build_transcript` returns `READY`/`HUMAN_REQUIRED` only; never calls an adapter/submit. `tests/test_dry_run_consistency.py`. |
| Dry-run — unresolved field → task + `would_submit=False` | **PASS** | Opens a `human_tasks` row; `would_submit` computed, not adapter-set. |
| Dry-run — résumé validation gate (P1-21) | **PASS (in-round)** | `build_transcript(..., resume_validation_status=...)`; a non-`PASS` artifact → résumé field not `FILLED`. `tests/test_dry_run_consistency.py::test_dry_run_blocks_when_resume_not_validated`. |
| Transcript payload determinism | **PASS** | Identical inputs → identical `payload["fields"]`. |
| Browser capture — CAPTCHA/MFA hard stop | **PASS** | CAPTCHA/MFA HTML → 0 fields, `blocking_reasons`, `human_required=True`, screenshot taken. No solver anywhere (`grep -rn captcha app/` = detection only). `tests/test_browser_capture_hardstop.py`. |
| LLM résumé tailoring | **N/A — no generator yet** | `JdAwareTailoringPlanner` only *selects* `fact_id`s (excludes `literal_only`/missing). No prose generation ⇒ fabrication not currently possible. Forward contract: `docs/LLM_RESUME_REVIEW_CONTRACT.md`. |
| PDF generation | **OPEN (P2-11)** | `render_simple_pdf` silently truncates lines to 110 chars, mangles non-latin-1 (`—`,`•`→`?`), no pagination/overflow detection, no `pdf_qa` module. Deterministic ✓, selectable text ✓. |
| Greenhouse / Lever / Ashby form adapters | **Not started** | Only `HtmlFormFieldExtractor` + `StaticAtsFieldProvider` (hand-written field lists). Dry runs today run against static guesses, not real DOM. |
| HTTP client (`Retry-After`, per-host, no-blind-POST-retry) | **Claimed, not test-verified** | `tests/test_http_client.py` still missing. |

---

## Verification tasks

### A. LLM résumé truth (WS2)
- [ ] Confirm no code path generates bullet prose yet. If/when it does, `LLM_RESUME_REVIEW_CONTRACT.md`
      §4 checklist applies: per-bullet `fact_ids`, number entailment, skill/tool subset, category lints,
      validator is separate code, regen cap 2 → `HUMAN_REQUIRED`.
- [ ] `JdAwareTailoringPlanner`: `literal_only` and `is_missing` facts never selected (verified by read).
- [ ] Add a red-team test the moment a generator lands (project→employment, leadership→management,
      familiarity→expertise, unsupported cloud tech, inflated counts, altered %).

### B. PDF ATS QA (WS3) — **P2-11 open**
- [ ] `render_simple_pdf` must not silently drop content: reject/flag a line > width, and any char
      outside the font's encoding.
- [ ] Add `app/resumes/pdf_qa.py` (`PDF_RESUME_QA.md` §2): selectable text, single column, headings,
      date format, page count, header/footer empty, non-ascii round-trip, deterministic hash,
      filename regex, text↔structured-source parity, required-fact presence.
- [ ] A failing `PdfQaResult` → `resume_artifact.validation_status = PDF_QA_FAILED` → application
      `HUMAN_REQUIRED`; the PDF never reaches an upload field.
- [ ] `tests/test_pdf_qa.py` xfails go green.

### C. Dry-run transcript consistency (WS4)
- [ ] Transcript payload includes `persona`, `requisition_key`, and (when browser capture is wired)
      screenshot + DOM snapshot paths. **(P2-10 — currently missing `persona`.)**
- [ ] A future submit path must recompute `payload_hash` and refuse if it changed after approval
      (`dry_run_transcripts` needs `approved_by/at`). **(P2-10)**
- [ ] Multi-category unresolved → one `human_task` **per category**, not just `blocking_reasons[0]`.
      **(P2-9 open.)**
- [ ] `test_dry_run_consistency.py`: transcript field value == the value the (future) browser adapter
      would type — add a cross-check once an adapter exists.

### D. Form engine red team (WS5) — **P1-22 / P1-23 PASS**
- [ ] Radio groups sharing a `name` are coalesced into one SELECT field (not N BOOL fields).
      **(P2-13 open — `html_form_extractor._kind_for` maps every radio to BOOL.)**
- [ ] Greenhouse/Lever/Ashby custom-question labels that don't use `<label for>` are captured from the
      sibling text / `<div class=label>` / `<legend>`. **(P2-14 open.)**
- [ ] Name with a single token → last-name field is `HUMAN_REQUIRED`, not `FILLED ""`. **(P2-15 open.)**
- [ ] Salary/relocation questions with a canonical answer available resolve from it instead of always
      `HUMAN_REQUIRED`. **(P3 — throughput, not safety.)**

### E. GH / Lever / Ashby dry-run review (WS6)
- [ ] Replace `StaticAtsFieldProvider` guesses with real capture via `BrowserFieldCapture` + fixtures
      per `BROWSER_ATS_STRATEGY.md`. Add `tests/fixtures/ats_forms/{greenhouse,lever,ashby}.html`.
- [ ] Per adapter: form detection, resume `input[type=file]` located, required detection, dynamic
      questions re-enumerated after select change, validation-error selectors, submit-button locator,
      confirmation detection, evidence extraction, `is_captcha_present` → `HUMAN_REQUIRED`.
- [ ] `stop-before-submit`: with `real_submission_enabled=false` the adapter builds the transcript and
      halts; `adapter.submit()` is never called. Test with a spy adapter.

### F. CAPTCHA / MFA / email verification (WS7) — hard stops **PASS at capture level**
- [ ] Wire `BrowserCaptureResult.human_required` into an application transition: `→ HUMAN_REQUIRED`
      with category `CAPTCHA`/`MFA`/`EMAIL_VERIFICATION` + a `human_task` + the screenshot path in
      `context`. **(currently the result object is returned but no state change happens.)**
- [ ] `EMAIL_VERIFICATION` gets its own category (today "verification code" → labelled `MFA`).
- [ ] No retry loop around a blocked page (`grep` the future adapter for a while/for around capture).

### G. Worker / reaper (WS8) — **P1-18 PASS**, one caveat
- [ ] **P1-24:** the "submit was sent" signal is a substring `SUBMIT_POST_SENT` in the free-text
      `notes` column. Move it to a dedicated `submit_attempted_at` timestamp set transactionally
      immediately before the submit click. A missed/overwritten note ⇒ post-submit crash routed to
      `RETRY_PENDING` ⇒ **duplicate submission**.
- [ ] Reaper covers a crash during each phase: pre-claim (atomic, fine), during fill (`APPLYING`,
      no note → `RETRY_PENDING`), after submit click (`APPLYING` + note → `SUBMISSION_UNKNOWN`),
      after `SUBMITTED` (no lease → verify-worker window). Add a test per phase.
- [ ] Stale worker returning after lease expiry: `lease_still_mine` False ⇒ it must abort before any
      side effect (verified for the primitive; re-verify once a real worker loop exists).

### H. HTTP client (WS9)
- [ ] Add `tests/test_http_client.py`: `Retry-After` honored on 429/503; per-host spacing; bounded
      retries; jitter present; timeout raises; **GET retried, POST/side-effecting never blind-retried**.
- [ ] Per-ATS bucket (GH/Lever 5 rps, Ashby 4 rps) — deferred until live adapters; note it.

### I. Submission verification red team (WS10) — **PASS** (fixtures)
- [ ] `tests/test_submission_verification_adversarial.py` covers: T1–T4 → `VERIFIED`; T5 alone → stays
      `SUBMITTED`; generic "Thank you" weak; HTTP 200 + validation error not verified; duplicate
      evidence → 1 transition; `SUBMISSION_UNKNOWN` + late T3 email → `VERIFIED`.
- [ ] Add: redirect to homepage / confirmation URL without application context → not strong.

### J. HUMAN_REQUIRED résumé flow (WS11)
- [ ] Task visible in `human_tasks`; resolving requires current status still `HUMAN_REQUIRED` (CAS).
- [ ] Wrong application cannot consume another's answer (task is keyed by `application_id`).
- [ ] Same question twice → one task (partial-unique index) — **PASS** (`test_human_task_atomicity.py`).
- [ ] Resolved task cannot be re-consumed (status `RESOLVED` excluded from open-task queries) — add test.
- [ ] `FormDryRunEngine` multi-category unresolved → one task per category (**P2-9**).

### K. Canary / DOM drift (WS12)
- [ ] `HtmlFormFieldExtractor` on a page with no form controls → empty list (**PASS** —
      `test_browser_capture_hardstop.py::test_no_form_on_page_produces_no_fields`). Caller must treat
      "0 fields but this is an apply page" as `ATS_CHANGED`, not proceed.
- [ ] An unrecognized challenge widget (Cloudflare Turnstile, `cf-challenge`) with no `captcha` token
      still blocks (**P2-12 open**).
- [ ] A daily canary per ATS against a real public posting, read-only, up to (not including) submit;
      selector/label mismatch → `ATS_CHANGED` alert, that adapter paused, others keep running.

### L. Performance (WS13)
- [ ] Once real timings exist (discovery, tailoring, PDF, browser startup, form fill, upload,
      validation, human-required rate), replace the estimates in `THROUGHPUT_MODEL.md` §8 with measured
      values. Do not extrapolate from guesses.

---

## Exit criteria for Round 3 sign-off

1. A (LLM truth), C (dry-run consistency incl. persona + hash-on-approval), D (form engine, incl.
   radio coalescing), F (hard-stop **state wiring**), J (HUMAN_REQUIRED flow) all **PASS**.
2. B (PDF QA module + gate) **PASS** — no résumé reaches an upload field without QA.
3. G caveat **P1-24** resolved (dedicated submit-attempted flag).
4. E: at least one ATS adapter does a real fixture-driven dry run that stops before submit, verified by
   a spy.
5. H: `tests/test_http_client.py` green.
6. Full suite green; every xpass promoted; new findings in `CLAUDE_REVIEW.md` with repro + fix + test.
7. `real_submission_enabled` **stays `false`**. Controlled real submission is a separate, human-gated
   decision after ≥3 reviewed dry-run transcripts per ATS.

**Not production-ready. Do not enable `real_submission_enabled`.**

---

## Codex follow-up status

**Verification:** `python3 -m pytest -q -rxX` → **321 passed, 1 skipped**.

### Fixed

- P1-24: submit-boundary recovery now uses durable `submit_attempted_at` semantics instead of free-text `notes`; expired post-submit leases route to `SUBMISSION_UNKNOWN`, while pre-submit crashes route to `RETRY_PENDING`.
- P2-9: dry runs now open one human task per distinct blocking category.
- P2-10: dry-run transcripts include `persona` and source-neutral `requisition_key`; approval/hash helpers are in place for the future submit gate.
- P2-11: PDF rendering no longer silently truncates long content, paginates generated PDFs, normalizes unsafe punctuation, and runs PDF QA before a resume artifact can be used.
- P2-12: browser hard stops transition applications to `HUMAN_REQUIRED` and open category-specific CAPTCHA/MFA/EMAIL_VERIFICATION tasks with screenshot context.
- P2-13: same-name radio groups are coalesced into one select-like field with options.
- P2-14: HTML extraction captures nearby/legend-style ATS labels before falling back to machine names.
- P2-15: required last-name fields block on single-token profile names instead of filling an empty string.
- HTTP client proof: tests now cover Retry-After seconds/date handling, per-host spacing, bounded retries, timeout wrapping, and no blind POST retry.
- Greenhouse/Lever/Ashby dry-run foundation: fixture-driven DOM adapters capture fields, build transcripts, gate bad PDFs, route hard stops, and prove submit is never called in dry-run.

### Deferred

- Controlled real submission remains deferred; `real_submission_enabled` stays `false`.
- Greenhouse live Playwright navigation foundation is implemented; exercising it against reviewed public postings is next.
- Live Lever and Ashby navigation remains deferred until Greenhouse live dry-run navigation is stable.
- Real LLM bullet generation remains deferred; the truth system and planning guardrails are in place first.

### Rejected

- None.
