# LLM_COST_STRATEGY.md — Token / Cost Review

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Context:** discovery can surface thousands of postings/day; only ~100–200 become applications. LLM spend
must scale with *applications*, not with *postings*.

---

## 1. Principle: a funnel of increasing cost

```
Stage 0  Deterministic filters        cost 0      runs on 100% of postings
Stage 1  Cheap structured extraction  cost $      runs on postings that pass Stage 0 (small model, batched)
Stage 2  Strong-model judgment        cost $$$    runs only when the decision is close AND the job is
                                                  otherwise apply-worthy
Stage 3  Resume/answer generation     cost $$     runs once per application (post-eligibility)
Stage 4  Entailment / validation      cost $      runs once per generated artifact (cheap model)
```
Rule: **no Stage-1+ call on a posting that Stage 0 can decide.** No Stage-2 call unless Stage-1 output is
ambiguous. Generation happens after a job is already ELIGIBLE + QUEUED, never speculatively.

---

## 2. Stage 0 — deterministic, no LLM (must decide the majority)

Runs in `app/filtering/hard_filters.py` + classifier + dedupe:
- job family via `role_taxonomy.yaml` keyword match on title/JD
- seniority, experience (requirements-region), citizenship-required, no-sponsorship, clearance,
  employment-type, US location
- exact + near dedupe (hash / requisition-number / simhash)

Target: **≥80% of postings** get a terminal ELIGIBLE/SKIPPED here with zero LLM cost. Track
`stage0_decision_rate`. If it drops, add deterministic rules before spending on LLM.

---

## 3. Stage 1 — cheap extraction (small/cheap model, batched)

Only for postings that pass Stage 0 but need structured understanding:
- normalize messy JD → `{seniority_signal, min_years, must_have_skills[], sponsorship_stance,
  location_us_bool, is_new_grad_program_bool, confidence}`
- one call per **batch of N postings** (e.g. 10–20) with a compact schema, `max_tokens` tight,
  structured/JSON output.
- **Input compression:** send title + the Requirements/Qualifications section + first ~1500 chars of JD,
  not the whole HTML. Strip nav/boilerplate/EEO paragraphs first (deterministic).
- **Caching:** key on `content_hash`. A re-discovered unchanged posting → cache hit, no call. A changed
  posting → re-extract only.
- Model: cheapest capable tier (e.g. Haiku-class). Never the strong model here.

---

## 4. Stage 2 — strong model, gated

Invoke **only if all** of:
- Stage 1 `confidence < threshold` OR Stage 1 flags conflict (e.g. title says "analyst", JD says "8 years")
- the posting is otherwise apply-worthy (family match, US/remote-US, not an obvious skip)
- daily Stage-2 budget not exhausted (hard cap; overflow → keep job as ELIGIBLE with `llm_review_pending`
  and revisit next cycle, or route to human if backlog large)

One posting per call, full relevant JD text, asks a single yes/no + reason: "Is this realistically open to
a graduating senior with no full-time experience?" Cache by `content_hash`.

Expected volume: single-digit % of Stage-1 postings.

---

## 5. Stage 3 — generation (once per application)

- Retrieval-built prompt: only the facts selected for this job (see `RESUME_TRUTH_SYSTEM.md` §3), not the
  whole profile, not the whole JD — JD is reduced to extracted `must_have_skills` + responsibilities.
- **Persona base reuse:** each persona has a fixed, pre-written base resume. The LLM only selects/reorders
  bullets and lightly rephrases within entailment limits → small output, small input.
- **Artifact cache:** key on `(persona, sorted(must_have_skills), profile_schema_version)`. Many postings
  in the same family with the same skill set → identical tailored resume → **1 generation, N reuses.**
  Expect high hit rate (analyst roles cluster hard).
- Cover letter only when the ATS field is required (see `ATS_MATRIX.md`); template + 2–3 generated
  sentences, cached similarly.
- Structured JSON output; `max_tokens` bounded to resume size.

---

## 6. Stage 4 — validation (cheap model, only residual claims)

- Deterministic checks first (free): provenance, skill/tool subset, number whitelist, closed-set terms,
  required-field presence.
- LLM entailment judge only for natural-language claims that survive deterministic checks — typically a
  few short claims per resume, batched into one call. Cheap model. Cache by `(claim, cited_fact_ids)`.

---

## 7. Cross-cutting cost controls

| Lever | How |
|---|---|
| **Hash-based reuse** | `content_hash` on every posting; cache all extraction/judgment keyed by it. Re-crawls of unchanged jobs cost $0. |
| **Batching** | Stage 1 and Stage 4 batch multiple items per call. |
| **Structured outputs** | JSON schema everywhere → no re-asking, no parsing retries, tight `max_tokens`. |
| **Prompt compression** | strip HTML/boilerplate/EEO/benefits sections deterministically before any call; send requirements region preferentially. |
| **Retrieval** | prompts carry only selected facts + extracted JD signals, never full profile / full JD. |
| **Prompt caching (provider)** | stable system prompt + persona base as a cached prefix across calls in a batch/day. |
| **Budgets & breakers** | per-stage daily $ cap + per-stage call counter in metrics; overflow degrades gracefully (defer, not drop; or human). |
| **Model tiering** | Stage 1/4 cheap tier; Stage 2/3 strong tier; never invert. |
| **Negative caching** | remember "this company/board template → boilerplate map" so extraction shrinks over time. |
| **Idempotent generation** | artifact cache keyed by persona+skills+schema_version; reguarantees reuse and reproducibility. |

---

## 8. Rough budget model (order-of-magnitude, tune with real prices)

Assume/day: 1,000 raw postings, 800 decided free at Stage 0, 200 to Stage 1, ~15 to Stage 2,
150 applications generated with ~70% artifact-cache hit ⇒ ~45 real generations, ~150 validations.

- Stage 1: 200 postings / batch 15 ≈ 14 calls, ~2–3k input tok each (compressed) → cheap tier, trivial.
- Stage 2: ~15 calls, ~4–6k input tok → strong tier, small.
- Stage 3: ~45 generations, ~2–4k in / ~1–1.5k out → strong tier, the largest line item but bounded by
  cache hit rate.
- Stage 4: ~150 residual-claim batches on cheap tier → trivial.

Dominant cost = Stage 3. The two biggest reducers: (a) persona-base + bullet-selection instead of
free-form generation, (b) the `(persona, skills, schema_version)` artifact cache. Both should be built in
from the start.

**Anti-patterns to reject in review:**
- Calling any LLM during discovery/crawl before Stage 0 filters run.
- One LLM call per posting for classification (must be batched, and only post–Stage 0).
- Sending full JD HTML or the full candidate profile in any prompt.
- Regenerating a resume per posting when family+skills are identical.
- Using the strong model for extraction or validation.
- No per-stage budget cap / no cost metrics.

---

## 9. OpenAI provider checkpoint (2026-09-07)

The first provider boundary is implemented with the OpenAI Responses API and remains disabled by
default. `OPENAI_API_KEY` is read from the process environment only; requests use `store: false`, have
a bounded output size and timeout, and are never blindly retried after an unknown network result.

Current routing defaults:

| Purpose | Model | Configured text price per 1M tokens (input / output) |
|---|---|---|
| Stage 1 extraction and Stage 4 validation | `gpt-5-nano` | $0.05 / $0.40 |
| Gated Stage 2/3 work | `gpt-5-mini` | $0.25 / $2.00 |

Prices are explicit router data and must be reviewed when provider pricing changes. The router records
the API's returned input/output token counts, derives cost from the model price table, caches identical
requests within the process, and rejects strong models in cheap-only stages. A date-keyed SQLite ledger
atomically reserves the worst-case request cost across workers before the API call and reconciles it to
actual usage afterward. Unknown models are estimated conservatively rather than treated as free.

`config/settings.yaml` keeps both `llm.enabled` and `llm.send_candidate_pii` false. Provider-backed
resume generation remains deferred until the prompt contract proves that only selected, provenance-
validated candidate facts are sent. `python3 "apply company.py" --llm-status` checks readiness without
making a paid API request.

Remaining cost-control work: durable content-hash response cache, structured-output contracts/evals,
and dashboard usage reporting.

### Selection-only tailoring contract

The first pipeline integration does not ask a model to author resume claims. After deterministic
Stage 0 and local keyword retrieval, `gpt-5-nano` may select a subset of allowed fact IDs. Identity,
contact, address, legal, missing, and literal-only facts are excluded from the request. The response
must be JSON containing exactly `selected_fact_ids`, all IDs must be from the supplied allowlist, and
the local deterministic generator retrieves the original fact wording. Invalid output or provider
failure falls back to the original deterministic selection. Resume artifacts record only model usage
and selection metadata, never the prompt or API key.
