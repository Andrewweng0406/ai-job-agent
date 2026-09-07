# Autonomous New-Grad Job Application Agent

Foundation for a safe, auditable, high-throughput system that discovers U.S. new-grad job
postings and prepares/submits applications with **verified** confirmation.

> Status: Phase 1-4 safety foundation. `real_submission_enabled: false`. No live submissions.
> Discovery, filtering, queueing, deterministic tailoring, PDF artifact generation, previews, and
> persisted dry-run transcripts are implemented. Browser automation remains no-submit/approval-gated work;
> page capture, HTML field extraction, Greenhouse/Lever/Ashby fixture-driven DOM dry-run adapters,
> and optional read-only Greenhouse live navigation are available.

## Principles

- If a job belongs to an accepted target family and the candidate is not clearly disqualified, it is
  generally eligible for the queue.
- The system never fabricates candidate information. Unknown info → `HUMAN_REQUIRED`.
- A clicked submit button is **not** success. Only evidence-backed `VERIFIED` counts.
- Deterministic filters first, cheap LLM extraction second, strong model only when it changes the outcome.

## Layout

| Path | Purpose |
|---|---|
| `app/` | pipeline stages: discovery, normalization, filtering, matching, applications, database |
| `config/` | candidate profile (source of truth), role taxonomy, company registry, safety settings |
| `tests/` | unit tests plus adversarial review suites |
| `docs/` | architecture, research, and the principal review log |

## Docs

- `docs/CLAUDE_REVIEW.md` — principal review log, P0–P3 findings, per-PR checklist
- `docs/JOB_SOURCE_RESEARCH.md` — discovery sources (Greenhouse/Lever/Ashby/Workday/…)
- `docs/ATS_MATRIX.md` — application-workflow compatibility matrix + build order
- `docs/FAILURE_MODEL.md` — failure taxonomy, recovery policy, unknown-submission protocol
- `docs/RESUME_TRUTH_SYSTEM.md` — fact-ID provenance + post-generation validation design
- `docs/LLM_COST_STRATEGY.md` — cost funnel and caching/batching strategy

## Develop

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Useful local commands:

```bash
python "apply company.py" --init-db
python "apply company.py" --discover --company-id <company_id> --show-new-jobs
python "apply company.py" --queue-eligible
python "apply company.py" --prepare-next --tailoring-mode FAST
python "apply company.py" --dry-run-next
python "apply company.py" --autofill-preview <dry_run_transcript_id>
python "apply company.py" --daily-report
```

Optional browser dry-run work uses Playwright:

```bash
python -m pip install -e ".[browser]"
python -m playwright install chromium
```

Current verification: `374 passed, 1 skipped`.
