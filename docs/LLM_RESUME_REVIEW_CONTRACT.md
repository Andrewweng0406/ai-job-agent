# LLM_RESUME_REVIEW_CONTRACT.md — Review Contract for LLM Résumé Tailoring

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Status:** review contract Codex's LLM tailoring MUST satisfy. Written before implementation so the
review is objective. Cross-refs `RESUME_TRUTH_SYSTEM.md`, `LLM_COST_STRATEGY.md`.

---

## 1. Required pipeline shape

```
JD (raw)
  → deterministic requirement extraction           (regex/keywords; no LLM if it decides)
  → persona selection                              (deterministic map from job_family)
  → fact retrieval                                 (select ONLY facts relevant to this JD + persona)
  → LLM tailoring                                  (bullet selection + light rephrase, constrained)
  → structured résumé representation               (JSON, per-bullet fact_ids + numbers)
  → truth / provenance validator                   (deterministic first, judge for residual)
  → PDF render                                     (PDF_RESUME_QA.md)
```

A review **fails** if any of these is true:
- an LLM call happens before deterministic requirement extraction ran
- the LLM prompt contains the **entire** candidate profile (must be retrieved subset)
- the LLM prompt contains the **entire** raw JD HTML (must be reduced to extracted requirements +
  responsibilities text)
- the résumé "source of truth" is the LLM output rather than the fact table
- generation is not cached on `(persona, sorted(required_skills), profile_schema_version)`

---

## 2. LLM input contract

Prompt carries **only**:
- persona id + the fixed persona base résumé (bullets are pre-vetted templates)
- retrieved facts, each as `{fact_id, type, text, numbers_in_fact:[…], literal_only:bool}`
- extracted JD signals: `must_have_skills[]`, `nice_to_have[]`, `responsibilities[]`, `seniority_signal`
- explicit constraints (see §3)

Prompt must **not** carry: other candidates' data, unrelated facts, raw HTML, PII beyond name, the
`literal_only` legal facts (those are never for generation).

## 3. Generation constraints (in the system prompt + enforced structurally)

1. **Cite or drop.** Each bullet returned as
   `{"text": "...", "fact_ids": ["project.pcb.3","skill.python"], "numbers": ["15"]}`.
   A bullet with `fact_ids == []` is dropped before validation.
2. **No new nouns of consequence.** No employer, tool, technology, certification, metric, or seniority
   term that is not in a cited fact.
3. **Numbers whitelist.** Every element of `numbers` must appear (after normalization) in the text of a
   cited fact. No new numbers, no rounding, no unit changes.
4. **No category mutation.** A `project` fact may not become an `experience`/employment claim; a
   `leadership` (student) fact may not become people-management; "used X" may not become "built
   production X"; "familiar with" may not become "expert in".
5. **Structured output only** (JSON schema); low temperature; deterministic seed where available.

## 4. Validator contract (what review runs against the LLM output)

Per bullet, in order — **any failure ⇒ reject bullet; ≤2 regen attempts; then `HUMAN_REQUIRED`**:

| Check | Rule |
|---|---|
| schema | has `text` + non-empty `fact_ids` (+ `numbers` list) |
| provenance | every `fact_id` ∈ retrieved-fact set for this job |
| skill/tool subset | every technology/tool token in `text` ∈ ⋃(cited facts' skills/tools) |
| number entailment | every `numbers[i]` normalized ∈ normalized numbers of a cited fact's text (`NUMERIC_PROVENANCE` rules — see `test_resume_numeric_provenance.py`) |
| closed-set | no term from forbidden closed-sets (`certifications: []`, `clearance: []`) appears |
| category | deterministic lints: `production`, `managed a team`, `led hiring`, `full-time`, `client(s)`, `senior`, `expert` etc. present ⇒ must be explicitly supported by a cited fact's own wording, else reject |
| omission | required résumé fields (name, school, degree, grad_date) present in the assembled doc |
| residual NL | anything not settled deterministically ⇒ entailment judge ("Is X fully supported by these facts? strict yes/no") ⇒ "no" or low-confidence ⇒ reject |

The validator must be **independent code**, not the same model call that generated the text.

## 5. Number classification (three-way)

Each number encountered must be classified:
- **SUPPORTED** — appears in a cited fact's text → allowed
- **UNSUPPORTED** — a performance/scope claim number not in any cited fact → reject
- **NON-CLAIM** — a version number, a calendar year, a course number, an address, a phone digit,
  "Python 3.11", "2026" grad year → not a metric; must not be in the bullet's `numbers` list and must
  not be validated as a metric. Detection: number adjacent to `version|v\d|20\d{2}|#|suite|apt|phone`,
  or in the education/contact sections.

## 6. Artifact + audit

`resume_artifact` stores: PDF, structured JSON source, model id, prompt hash, retrieved `fact_ids`,
validator version, full `validation_report` (`{bullet, cited_fact_ids, per-check verdicts}`).
`explain_resume(resume_id)` renders bullet → facts → verdicts. Regeneration with identical inputs
reproduces the artifact (hash-stable).

## 7. Review checklist (paste into the PR review)

- [ ] deterministic extraction + persona select run before any LLM call
- [ ] prompt = retrieved subset only (assert size bounds; no full profile, no raw HTML)
- [ ] output is structured with per-bullet `fact_ids` + `numbers`
- [ ] `fact_ids == []` bullet dropped; unknown `fact_id` ⇒ reject
- [ ] number entailment enforced (SUPPORTED/UNSUPPORTED/NON-CLAIM) — `test_resume_numeric_provenance.py` green
- [ ] skill/tool subset + closed-set + category lints enforced
- [ ] validator is separate code from the generator call
- [ ] regen capped at 2, then `HUMAN_REQUIRED` (`TRUTH_VALIDATION_FAILED`)
- [ ] artifact + `validation_report` + `explain_resume` present
- [ ] generation cache keyed `(persona, skills, schema_version)`; hit rate reported
- [ ] no résumé ships while any `required` profile fact is `TODO` (completeness gate)
