# ATS_MATRIX.md — Application Workflow Compatibility Matrix

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Purpose:** decide adapter build order for high-throughput *legitimate* applications.

Scoring: Low / Medium / High effort or risk. "Automation reliability" = expected share of attempts that reach a verified submission without human help, on a mature adapter.

---

## 1. Matrix

| ATS | Discovery difficulty | Application difficulty | Account required? | Resume upload | Custom questions | CAPTCHA risk | MFA risk | Automation reliability | Submission verification method | Priority |
|---|---|---|---|---|---|---|---|---|---|---|
| **Greenhouse** (hosted apply, `job-boards.greenhouse.io` / `boards.greenhouse.io`) | Low | Low–Med | **No** (email-only) | Yes (file field, sometimes resume-parse autofill) | Few–moderate; some EEO + custom dropdowns | Low (occasional hCaptcha on high-volume boards) | None | **High** | Confirmation page + "application received" screen; confirmation email to candidate mailbox | **P1 (build first)** |
| **Lever** (`jobs.lever.co/{co}/{id}/apply`) | Low | Low | **No** | Yes | Few; some custom + EEO | Low | None | **High** | Post-submit "Thank you" page; confirmation email | **P1** |
| **Ashby** (`jobs.ashbyhq.com/{co}/{id}`) | Low | Low–Med | **No** (some orgs optional account) | Yes | Moderate; structured question types (yes/no, select, long text) | Low | None | **High** | Confirmation screen + email; GraphQL response contains application id | **P1** |
| **SmartRecruiters** (`jobs.smartrecruiters.com` / `careers.smartrecruiters.com`) | Low | Medium | Sometimes (SmartApply; social/email) | Yes | Moderate; screening questions with knockout logic | Low–Med | Low | Medium–High | Confirmation page + email; candidate portal shows application | **P2** |
| **Workable** (`apply.workable.com/{co}/j/{shortcode}`) | Low | Low–Med | **No** | Yes | Few–moderate; per-job custom questions | Low (reCAPTCHA v2 on some) | None | Medium–High | "Application submitted" page + email | **P2** |
| **Workday** (`{tenant}.wdN.myworkdayjobs.com`) | Medium | **High** | **Yes** (account per tenant; email verify) | Yes (+ aggressive resume parser prefills, often wrong) | **Many**; multi-step wizard, voluntary disclosures, per-tenant questions | Low–Med | Med (email verification link; some tenants add step-up) | **Low–Medium** | Authenticated "My Applications" / "Candidate Home" shows submitted req; confirmation email; sometimes confirmation number | **P3 (high value, do after P1/P2 stable)** |
| **iCIMS** (`careers-{co}.icims.com`) | High | High | Usually (profile + email verify) | Yes | Many; varies per portal template | Med | Med | Low | Candidate portal application list; confirmation email | P4 |
| **Taleo / Oracle ORC** | High | High | Yes | Yes | Many; long multi-page flows | Med | Med | Low | Portal "submission complete" + candidate profile list | P4 |
| **Jobvite** (`jobs.jobvite.com` / `app.jobvite.com`) | Medium | Medium | Sometimes | Yes | Moderate | Med (reCAPTCHA common) | Low | Medium | Confirmation page + email | P3 |
| **BambooHR** (`{co}.bamboohr.com/careers`) | Low | Low | No | Yes | Few | Low | None | Medium–High | "Thanks for applying" page + email | P3 |
| **Recruitee** (`{co}.recruitee.com`) | Low | Low | No | Yes | Few–moderate | Low | None | Medium–High | Confirmation page + email | P3 |
| **Rippling ATS** (`ats.rippling.com`) | Medium | Low–Med | No | Yes | Moderate | Low | None | Medium | Confirmation page + email | P3 |
| **USAJOBS → agency system (USA Hire / Monster Gov / etc.)** | Low (API) | **Very High** (hand-off to agency portal, assessments) | Yes (Login.gov) | Yes | Many + assessment questionnaires | Med | **High** (Login.gov MFA) | Very Low (mostly human) | USAJOBS "application status" + agency portal | P4 (mostly HUMAN_REQUIRED) |
| **Company-custom / homegrown forms** | High (per-site) | Varies | Varies | Varies | Varies | Varies | Varies | Low (bespoke) | Whatever the page provides; often weak → UNKNOWN-prone | P4 (case-by-case) |

---

## 2. Recommended build order & rationale

1. **Greenhouse, Lever, Ashby (P1).** No account, clean hosted apply forms, stable DOM, public discovery APIs, reliable confirmation page + email. This is where the first ~60–70 verified submissions/day realistically come from. One adapter each; shared form-fill primitives.
2. **Workable, SmartRecruiters (P2).** Still mostly no-account, moderate custom questions, decent confirmation signals. Adds volume and company diversity.
3. **Workday (P3, highest strategic value).** Most new-grad *programs* live here. Requires: per-tenant account creation + email verification, a robust multi-step wizard driver, tolerance for per-tenant field variance, and heavy use of `verify()` via authenticated "My Applications". Budget real engineering time; expect lower reliability and more `HUMAN_REQUIRED`.
4. **BambooHR, Recruitee, Rippling, Jobvite (P3).** Long tail, cheap-ish adapters, incremental volume.
5. **iCIMS, Taleo/ORC, USAJOBS-agency, custom (P4).** High effort, low reliability. Mostly route to `HUMAN_REQUIRED` with a pre-filled draft where possible.

---

## 3. Adapter interface (every ATS must implement)

```python
class AtsAdapter(Protocol):
    provider: str
    def discover(self, company) -> Iterable[RawPosting]: ...
    def normalize(self, raw: RawPosting) -> Job: ...
    def apply(self, job: Job, persona: Persona, resume: ResumeArtifact) -> ApplyResult: ...
    def verify(self, apply_result: ApplyResult) -> Verification: ...  # VERIFIED | UNKNOWN | FAILED
```
Mandatory behaviors:
- `apply()` writes the idempotency row (`application_key`, status `IN_PROGRESS`) **before** interacting with the form.
- On CAPTCHA / MFA / bot wall / unknown legal question / unmapped required field → return `ApplyResult(status=HUMAN_REQUIRED, reason=..., snapshot=...)`. No solving, no evasion.
- On every failure and every `UNKNOWN`: capture screenshot + DOM + URL + step index.
- Hard per-application timeout (e.g. 6 min); on timeout with a submit already fired → `SUBMITTED_UNVERIFIED` → verify loop, never re-submit.
- `verify()` must return an evidence tier (confirmation id / email match / portal entry / API id) or `UNKNOWN`.

---

## 4. Verification method per tier (reuse across adapters)

| Tier | Mechanism | Notes |
|---|---|---|
| T1 confirmation id | Regex/DOM capture of "confirmation #", "requisition", "application id" on success page | Strongest; store verbatim |
| T2 email match | IMAP poll of candidate mailbox; match sender domain + company + role + time window (±30 min) | Async; verification worker, not the apply worker |
| T3 portal entry | Authenticated re-load of "My Applications"; assert req present | Only Workday/iCIMS/Taleo/SmartRecruiters-with-account |
| T4 API/GraphQL id | Inspect network response from the submit call for an application/candidate id | Ashby, Greenhouse hosted, Workday CXS |
| — none in window | → `UNKNOWN` → `human_tasks` | Never counts toward daily target |

---

## 5. Risk notes

- **CAPTCHA:** treat any appearance as a hard stop for that attempt. Rising volume from one IP raises CAPTCHA rate — another reason for conservative pacing and per-domain limits, not for evasion tooling.
- **MFA / email verification (Workday, iCIMS, Login.gov):** automate only the parts that are the candidate legitimately clicking their own verification link from their own mailbox; anything requiring a phone code or authenticator → `HUMAN_REQUIRED`.
- **Resume parsers prefill wrong data (Workday especially):** always diff parsed fields against profile facts and correct them before submit; log diffs.
- **DOM drift:** ATS UI changes silently. Each adapter needs selector resilience (role/label-based locators, not brittle CSS) and a canary test per provider run daily against a real posting up to the review-before-submit step (never actually submitting in canary).
```
