# Autonomous New-Grad Job Application Agent

Foundation for a safe, auditable, high-throughput system that discovers U.S. new-grad job
postings and prepares/submits applications with **verified** confirmation.

> Status: Phase 1–2 foundation. `real_submission_enabled: false`. No live submissions. No browser
> automation. Discovery adapters are being built against public/structured ATS endpoints only.

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
| `tests/` | unit tests + `test_adversarial_*.py` (adversarial suite; `xfail` = tracked gap) |
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
