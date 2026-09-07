# RESUME_TRUTH_SYSTEM.md — Truthfulness Design

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Invariant:** the system must be able to answer, for every sentence on a generated resume and every
application answer: **"Which candidate fact(s) permit this to appear, and does it overstate them?"**
If it cannot, the sentence does not ship — it becomes `HUMAN_REQUIRED`.

Current code (`app/resumes/truth_validation.py`) is a placeholder (exact string match). This document is
the target design.

---

## 1. Threat model (what "fabrication" looks like)

| Class | Example | Guard |
|---|---|---|
| Invented skill | "Proficient in AWS" with no AWS fact | skill allowlist from profile |
| Invented tool/tech | "Built with Kafka" — never used Kafka | tool allowlist |
| Inflated metric | fact: "improved query speed"; bullet: "improved query speed by 60%" | number provenance check |
| Invented scope/scale | fact: "class project, 3 people"; bullet: "led team of 12" | entity/number check |
| Invented employer/title | job never held | experience entries are closed-set |
| Invented dates / overlap | graduation moved earlier; fake tenure | date facts are literal |
| Credential claim | "AWS Certified", "Series 7", "CFA L1" | certifications are closed-set |
| Clearance / citizenship claim | "US Citizen", "Active Secret" | legal facts literal, never generated |
| Implied seniority | "Senior analyst responsibilities" | phrasing lint |
| Omission that misleads | dropping graduation date to look already-graduated | required-field presence check |
| Answer fabrication | "No, I don't require sponsorship" | answers come only from `application_answers` facts |

---

## 2. Master Candidate Profile — fact model

Replace the flat YAML with addressable facts. Every atomic, checkable claim is one record.

```yaml
# config/candidate_profile.yaml
meta:
  candidate_id: cand_0001
  schema_version: 2
facts:
  - fact_id: name.full
    type: identity
    value: "Jane Q. Student"
    required: true
    evidence: "self-attested"
  - fact_id: edu.bs.school
    type: education
    value: "San Jose State University"
    required: true
  - fact_id: edu.bs.degree
    type: education
    value: "B.S. Business Analytics"
    required: true
  - fact_id: edu.bs.grad_date
    type: education
    value: "2026-05"
    required: true
  - fact_id: edu.bs.gpa
    type: education
    value: "3.6"
    required: false
  - fact_id: skill.sql
    type: skill
    value: "SQL"
    proficiency: "intermediate"
    evidence: ["proj.retail_dashboard", "exp.campus_analytics"]
  - fact_id: skill.python
    type: skill
    value: "Python"
    proficiency: "intermediate"
  - fact_id: proj.retail_dashboard
    type: project
    title: "Retail Sales Dashboard"
    role: "individual course project"
    team_size: 1
    tools: ["SQL", "Tableau", "Python"]
    metrics:
      - metric_id: proj.retail_dashboard.rows
        claim: "analyzed ~50,000 transaction records"
        basis: "dataset row count, verified"
      - metric_id: proj.retail_dashboard.time_saved
        claim: "reduced manual reporting time from ~2 hrs to ~15 min for the class"
        basis: "self-measured, course context"
    bullets_allowed:
      - "Built an interactive Tableau dashboard on ~50K retail transactions to surface weekly sales trends."
  - fact_id: exp.campus_analytics
    type: experience
    employer: "SJSU Student Success Center"
    title: "Data Analyst Intern"
    start: "2025-06"
    end: "2025-08"
    team_size: 4
    tools: ["SQL", "Excel", "Python"]
    responsibilities_verified:
      - "cleaned and joined enrollment datasets"
      - "produced weekly retention reports for staff"
  - fact_id: auth.status
    type: legal
    value: "F-1 student, work-authorized via CPT/OPT"
    required: true
    literal_only: true          # never paraphrased or generated; used only to answer explicit questions
  - fact_id: auth.needs_future_sponsorship
    type: legal
    value: true
    required: true
    literal_only: true
  - fact_id: certifications
    type: closed_set
    value: []                   # empty = the system may never claim any certification
  - fact_id: clearance
    type: closed_set
    value: []                   # empty = never claim any clearance
application_answers:            # canonical answers, human-authored, for known questions
  work_authorized_us: "Yes"
  requires_sponsorship_now_or_future: "Yes"
  willing_to_relocate: "Yes"
  gender / race / veteran / disability: "Decline to self-identify"   # unless human overrides
```

Rules:
- `type: closed_set` with `value: []` means **the corresponding claim class is forbidden** in output.
- `literal_only: true` facts are never fed to the generator; they are only consulted by the answer engine
  for exact questions, and their value is inserted verbatim.
- `metrics[].claim` strings are the **only** quantified statements allowed; the generator may not introduce
  a number that is not present in some `metric.claim` (or a date/GPA/team_size fact).
- `bullets_allowed` (optional) are pre-vetted, human-approved bullet texts — the safest path; the
  generator's job is selection + light rephrasing within entailment limits, not invention.

---

## 3. Generation constraints (before the model runs)

1. **Retrieval, not free recall.** Build the prompt from the specific facts selected for this job
   (persona + JD keyword match against `skill`/`tool`/`project`/`experience` facts). The model sees only
   those facts, each with its `fact_id`.
2. **Cite or omit.** The model must emit, per bullet, `{"text": ..., "fact_ids": [...], "numbers": [...]}`.
   A bullet with no `fact_ids` is dropped.
3. **No new nouns of consequence.** System prompt forbids introducing employers, tools, technologies,
   certifications, metrics, or seniority claims not in the provided facts.
4. **Numbers whitelist.** Any digit-bearing claim must reference a `metric_id` / date / gpa / team_size
   fact by id.
5. **Structured output** (JSON schema) so validation is mechanical.
6. **Temperature low**, deterministic seeds where available, for reproducibility.

---

## 4. Post-generation validation (the gate)

Pipeline per candidate output (resume bullets + cover letter + free-text answers):

```
1. Schema check        — each item has text + fact_ids (+ numbers[])
2. Provenance check     — every fact_id exists in the profile; belongs to a fact selected for this job
3. Claim decomposition  — split each bullet into atomic claims (skill use, action, tool, metric, scope)
4. Entailment check     — for each atomic claim, is it entailed by the cited fact(s)?
                          a) deterministic first:
                             - skill/tool mentioned ⊆ union(cited facts' tools/skills)
                             - employer/title/date strings == literal facts
                             - every number ∈ cited metric.claim / date / gpa / team_size
                             - no term from the forbidden closed-sets (certs, clearance) appears
                          b) LLM entailment judge (cheap model) for the residual natural-language claims,
                             asked strictly: "Is X fully supported by these facts? yes/no + why", no benefit
                             of the doubt.
5. Phrasing lint        — regex/classifier for seniority inflation ("senior", "lead", "spearheaded a large
                          team"), vague scale ("enterprise-scale", "millions of users") absent a fact
6. Omission check       — required:true facts that MUST appear on a resume (name, school, degree,
                          grad_date) are present; if a role asks for GPA and gpa fact absent → leave blank,
                          never invent
7. Answer check         — every application answer maps to application_answers[key] or a literal legal fact;
                          anything else → HUMAN_REQUIRED
```

Outcome:
- All pass → artifact is eligible to submit; store `resume_artifact{pdf, json_source, model, prompt_hash,
  cited_fact_ids[], validator_version, validation_report}`.
- Any deterministic failure → **regenerate ≤2×** with the offending claim explicitly forbidden.
- Still failing, or any entailment "no" the regen can't fix, or an omission of a required field →
  `HUMAN_REQUIRED` with the specific claim and the missing/again fact.
- **Never** ship an unvalidated artifact. `real_submission_enabled` gate + `profile_completeness_gate`
  must both be satisfied.

---

## 5. Provenance & auditability

- Persist `validation_report` per artifact: list of `{claim, cited_fact_ids, verdict, method}`.
- Given any shipped resume, a human can run `explain_resume(resume_id)` → table of every bullet → facts →
  verdict. This directly answers the invariant question.
- Store the exact prompt (hashed) + model id + profile `schema_version`. Regeneration with the same inputs
  reproduces the same artifact (cost + audit).
- Log `truth_validation_failures` metric by class (§1) — a rising trend means the generator or prompt
  regressed.

---

## 6. What is explicitly out of scope for automation

- Editing/adding facts to the profile — human only.
- Answering any legal/authorization/EEO question not present verbatim in `application_answers` — always
  `HUMAN_REQUIRED`.
- "Optimistic rounding" of metrics — forbidden; a number is either a cited fact or absent.
- Cover letters that assert anything not on the validated resume.

---

## 7. Minimum viable version (to unblock Phase 3 resume work)

1. Profile v2 with `fact_id`s + `application_answers` + closed-sets (config only, no code risk).
2. `profile_completeness_gate()` — refuse generation/submission while any `required: true` fact is TODO.
3. Structured generation output (`text` + `fact_ids` + `numbers`).
4. Deterministic validator: provenance + skill/tool subset + number whitelist + forbidden closed-set terms
   + required-field presence. (Skip the LLM entailment judge in v1; route its cases to HUMAN_REQUIRED.)
5. `explain_resume()` report.
6. Tests: the ADV-14/ADV-15/ADV-16 cases in `tests/test_adversarial_truth.py`.

This is a launch blocker per `CLAUDE_REVIEW.md` P0-3 / P1-5 — resume generation may not ship without §7.
