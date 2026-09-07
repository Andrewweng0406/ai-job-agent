# THROUGHPUT_MODEL.md — Performance Model

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Question:** what does it take to reach **100 verified submissions/day** (stretch **150**)?

All numbers are planning estimates to be replaced with measured values once the P1 adapters run. The
model exists to find the bottleneck, not to predict to two decimals.

---

## 1. The funnel

```
raw postings discovered
      │  x  keep_rate (US + target family + fresh)
eligible postings
      │  x  queue_yield (dedupe survivors, persona resolved)
queued applications
      │  x  reachable_rate (adapter supports ATS, posting still open at apply time)
apply attempts
      │  x  submit_rate (form completed + submit fired, no HUMAN_REQUIRED / hard fail)
submitted (unverified)
      │  x  verify_rate (evidence tier met within window)
VERIFIED  ◄── the KPI
```

---

## 2. Assumptions (P1 adapters: Greenhouse + Lever + Ashby, mature)

| Parameter | Pessimistic | Expected | Optimistic |
|---|---|---|---|
| `keep_rate` (raw → eligible) | 0.10 | 0.15 | 0.20 |
| `queue_yield` (eligible → queued, after dedupe/persona) | 0.60 | 0.70 | 0.80 |
| `reachable_rate` (queued → attempt) | 0.80 | 0.90 | 0.95 |
| `submit_rate` (attempt → submitted) | 0.70 | 0.82 | 0.90 |
| `verify_rate` (submitted → verified) | 0.80 | 0.90 | 0.95 |
| **net attempt → verified** | **0.56** | **0.74** | **0.855** |
| `human_required_pct` of attempts | 25% | 12% | 6% |
| `retry_pct` of attempts (transient, pre-submit) | 20% | 10% | 5% |
| avg form completion time (no-account: GH/Lever/Ashby) | 5.0 min | 3.5 min | 2.5 min |
| avg form completion time (account ATS: Workday) | 14 min | 9 min | 6 min |
| per-application hard timeout | 6 min (no-acct) / 15 min (acct) | | |

---

## 3. What 100 verified/day requires

Using **expected** net attempt→verified = **0.74**:

- **apply attempts/day** = 100 / 0.74 ≈ **135** (pessimistic 0.56 → **179**; optimistic → **117**).
- **queued/day** = 135 / 0.90 ≈ **150**.
- **eligible postings/day** = 150 / 0.70 ≈ **214**.
- **raw postings/day** = 214 / 0.15 ≈ **1,430** (pessimistic keep_rate 0.10 → **2,140**).
- Plus ~135 × 12% ≈ **16 human tasks/day** to service, and ~135 × 10% ≈ **14 retries/day** (extra attempts already folded into `submit_rate`, but they consume worker time).

For **150 stretch**: multiply the chain by 1.5 → ~**203 attempts**, ~**225 queued**, ~**320 eligible**,
~**2,150–3,200 raw postings/day**, ~**24 human tasks/day**.

**Registry implication:** at a 6–12 h crawl cadence, 1,430 fresh-relevant raw postings/day means roughly
**900–1,600 active company boards** (many boards yield 0–2 target-family new-grad roles per day).
Registry size, not crawl speed, is the primary throughput lever.

---

## 4. Worker sizing

### Application workers (the bottleneck)
Effective throughput per worker:
`60 min / (avg_form_time / submit_rate + overhead)`.
- No-account, expected: `3.5 / 0.82 + 0.7 overhead` ≈ **4.97 min/attempt** → ~**12 attempts/hour/worker**.
- Over a **10-hour** operating window: **120 attempts/worker/day**.

| Target | Attempts/day needed | No-account workers @120/day | With 30% Workday mix |
|---|---|---|---|
| 100 verified | ~135 | **2** workers (buffer to 3) | 3–4 workers |
| 150 verified | ~205 | **2–3** workers (buffer to 4) | 4–5 workers |

`application_concurrency` in settings is currently **1** → **hard cap ≈ 120 attempts/day ≈ 80–90
verified/day** best case. **Raise to 3–4** once idempotency + per-domain limiting are solid
(see `CLAUDE_REVIEW.md`).

### Discovery workers
1,430–3,200 raw postings from ~1,000–1,600 boards. One board fetch ≈ 0.3–1.5 s + politeness delay.
At `discovery_concurrency: 2` with a 1 req/s per-host cap and shared global ~5 req/s: a full sweep of
1,200 boards ≈ **20–40 min**. **2–3 discovery workers** is plenty; discovery is not the bottleneck.

### Resume workers
~150 generations/day, ~70% served from the `(persona, skills, schema_version)` artifact cache → ~**45
real generations/day**. `resume_concurrency: 2` is fine.

### Verify workers
Async, mostly IMAP polls + occasional re-auth. 135 in-flight verifications with 45-min windows →
1 worker handles it; run **2** for redundancy.

---

## 5. Per-domain concurrency

| ATS | Max concurrent per company/tenant | Global cap for the ATS | Notes |
|---|---|---|---|
| Greenhouse | 2 | ~5 req/s | Public API is tolerant; still jitter. |
| Lever | 2 | ~5 req/s | |
| Ashby | 2 | ~4 req/s | Smaller infra; be gentle. |
| Workday | **1 per tenant** | ~2 req/s | Sensitive; serialize per tenant, long jitter. |
| SmartRecruiters | 2 | documented soft limits | |

Application submissions to a single company: **1 at a time**, with a cooldown after any CAPTCHA/block.

---

## 6. Bottleneck summary & levers

1. **`application_concurrency = 1`** → lift to 3–4. Biggest single unlock (80 → 130+ verified/day headroom).
2. **Registry size** → need ~1,000–1,600 active boards for 100/day; ~2,000+ for 150/day.
3. **`submit_rate`** (form automation robustness) → each +5% is ~7 fewer attempts/day needed.
4. **`human_required_pct`** → drives the human's daily workload (~16 tasks/day at 12%); keep the
   classifier tight so it doesn't balloon.
5. **Operating window** — model assumes 10 h/day of active application work; a 16 h window relaxes worker
   count but raises anti-bot exposure per IP (mitigate with pacing, not evasion).

## 7. Cost sanity (cross-ref `LLM_COST_STRATEGY.md`)

LLM spend scales with ~150 applications/day and ~215 Stage-1 extractions/day, not with 1,430 raw
postings (Stage 0 decides ~80% for free). Dominant line is ~45 resume generations/day.
