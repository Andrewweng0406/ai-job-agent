# FORM_FIELD_TAXONOMY.md — ATS Form Field Mapping

**Author:** Claude (reviewer)
**Updated:** 2026-09-06
**Purpose:** a reusable, ATS-agnostic mapping from application form fields → candidate data source →
fill policy. Adapters import this; they do not invent per-ATS logic for common fields.

---

## 1. Fill-policy classes

| Class | Meaning | Behavior |
|---|---|---|
| `AUTO_SAFE` | Value is non-sensitive and either constant or trivially derived. | Fill automatically; log value. |
| `PROFILE_REQUIRED` | Must come from a specific `fact_id` in the Master Candidate Profile. If that fact is `TODO`/absent → block. | Fill from fact; if missing → `HUMAN_REQUIRED` (`PROFILE_INCOMPLETE`). |
| `HUMAN_REQUIRED` | Judgment, free-text essays, or anything the profile cannot deterministically answer. | Do not fill. Open a human task with the verbatim field label + options. |
| `NEVER_GUESS` | Legal/eligibility attestations and demographic questions. Wrong or fabricated answers are integrity violations. | Fill ONLY from an explicit, human-authored canonical answer (`application_answers` / `literal_only` fact). Any ambiguity, novel phrasing, or missing canonical answer → `HUMAN_REQUIRED`. Never infer. |

Precedence when a field could match two classes: `NEVER_GUESS` > `HUMAN_REQUIRED` > `PROFILE_REQUIRED` > `AUTO_SAFE`.

---

## 2. Field catalog

### Identity / contact
| Field | Class | Source (`fact_id` / key) | Notes |
|---|---|---|---|
| First name | `PROFILE_REQUIRED` | `name.full` (split) | Split on last space; keep suffixes with last name. |
| Last name | `PROFILE_REQUIRED` | `name.full` (split) | |
| Full / preferred name | `PROFILE_REQUIRED` | `name.full` / `name.preferred` | |
| Email | `PROFILE_REQUIRED` | `contact.email` | Use the candidate mailbox that verification polls. |
| Phone | `PROFILE_REQUIRED` | `contact.phone` | Normalize to E.164; some ATS want `(xxx) xxx-xxxx`. |
| Phone type (mobile/home) | `AUTO_SAFE` | constant `Mobile` | |

### Address / location
| Field | Class | Source | Notes |
|---|---|---|---|
| Street address line 1/2 | `PROFILE_REQUIRED` | `contact.address.line1/line2` | Some ATS require it even for remote roles. |
| City | `PROFILE_REQUIRED` | `contact.address.city` | |
| State / Province | `PROFILE_REQUIRED` | `contact.address.state` | Map to the ATS's exact option string (2-letter vs full). |
| ZIP / Postal code | `PROFILE_REQUIRED` | `contact.address.postal` | |
| Country | `PROFILE_REQUIRED` | `contact.address.country` = `United States` | |
| Current location (free text) | `PROFILE_REQUIRED` | derived `city, state` | |
| "Are you within commuting distance of X?" | `HUMAN_REQUIRED` | — | Depends on the specific office + relocation intent. |

### Education
| Field | Class | Source | Notes |
|---|---|---|---|
| School / University | `PROFILE_REQUIRED` | `edu.primary.school` | Fuzzy-match to ATS typeahead; if no match → `HUMAN_REQUIRED` (`FORM_MAPPING`). |
| Degree type | `PROFILE_REQUIRED` | `edu.primary.degree_type` (e.g. `Bachelor's`) | Map to ATS option set. |
| Field of study / Major | `PROFILE_REQUIRED` | `edu.primary.major` | |
| Minor | `AUTO_SAFE` if present else skip | `edu.primary.minor` | Optional; leave blank if absent. |
| GPA | `PROFILE_REQUIRED` if field is required, else `AUTO_SAFE` | `edu.primary.gpa` | If required and `gpa` fact absent → `HUMAN_REQUIRED`. Never invent, never round up. |
| Start date | `PROFILE_REQUIRED` | `edu.primary.start_date` | |
| Graduation date (month/year) | `PROFILE_REQUIRED` | `edu.primary.grad_date` | Future date is expected (candidate is a senior). Do NOT omit to look already-graduated. |
| Expected vs completed | `AUTO_SAFE` | derived: `Expected` if grad_date > today | |
| Currently enrolled? | `AUTO_SAFE` | derived from dates | |

### Work authorization / sponsorship — ALL `NEVER_GUESS`
| Field (canonical intent) | Class | Canonical answer key | Notes |
|---|---|---|---|
| "Are you legally authorized to work in the United States?" | `NEVER_GUESS` | `application_answers.work_authorized_us` | For an F-1 with CPT/OPT this is typically `Yes` — but it is a **human-set fact**, not inferred. |
| "Will you now or in the future require sponsorship for employment visa status (e.g. H-1B)?" | `NEVER_GUESS` | `application_answers.requires_sponsorship_now_or_future` | International student → `Yes`. |
| "Do you now require sponsorship?" (present-only) | `NEVER_GUESS` | `application_answers.requires_sponsorship_now` | Often `No` while on CPT/OPT — still human-set. |
| "Are you a U.S. citizen or permanent resident?" | `NEVER_GUESS` | `application_answers.us_citizen_or_pr` | Usually `No`. If the role *requires* it, the job should have been hard-filtered upstream. |
| "Describe your immigration status / any work restrictions" (free text) | `HUMAN_REQUIRED` | — | Never auto-fill a legal free-text field. |
| Any authorization question whose phrasing the classifier maps with < 0.95 confidence | `HUMAN_REQUIRED` | — | Fail closed. |

### Relocation / logistics
| Field | Class | Source | Notes |
|---|---|---|---|
| "Willing to relocate?" | `PROFILE_REQUIRED` | `application_answers.willing_to_relocate` | |
| "Willing to relocate to [specific city]?" | `HUMAN_REQUIRED` if profile answer isn't an unconditional yes | `application_answers.willing_to_relocate` | Unconditional `Yes` → `AUTO_SAFE`. |
| "Open to remote / hybrid / onsite?" | `PROFILE_REQUIRED` | `application_answers.work_mode_pref` | |
| Earliest start date | `PROFILE_REQUIRED` | derived from `edu.primary.grad_date` (+ buffer) | |
| Notice period | `AUTO_SAFE` | constant `None / student` | |

### Compensation
| Field | Class | Source | Notes |
|---|---|---|---|
| Desired salary (numeric) | `PROFILE_REQUIRED` | `comp.target_base` | If absent and field required → `HUMAN_REQUIRED`. |
| Desired salary (free text) | `HUMAN_REQUIRED` | — | Free text ("negotiable", ranges, rationale) is judgment. See `HUMAN_QUEUE_DESIGN.md`. |
| "Salary expectations acceptable? min $X" (knockout) | `HUMAN_REQUIRED` | — | Answering wrong can auto-reject or misrepresent. |
| Hourly rate (contract) | `HUMAN_REQUIRED` | — | Usually out of target scope anyway. |

### Demographic / EEO — ALL `NEVER_GUESS` (default decline)
| Field | Class | Default | Notes |
|---|---|---|---|
| Gender | `NEVER_GUESS` | `Decline to self-identify` | Only override if candidate explicitly set `application_answers.eeo_gender`. |
| Race / ethnicity | `NEVER_GUESS` | `Decline to self-identify` | |
| Veteran status | `NEVER_GUESS` | `I don't wish to answer` | |
| Disability status | `NEVER_GUESS` | `I don't wish to answer` | |
| Hispanic/Latino | `NEVER_GUESS` | `Decline` | |
| Pronouns | `AUTO_SAFE` if `application_answers.pronouns` set, else skip/blank | — | Never guess from name. |

### Experience
| Field | Class | Source | Notes |
|---|---|---|---|
| "Years of relevant experience" (numeric) | `PROFILE_REQUIRED` | `exp.total_years` (may be `0`) | Answer honestly with `0` / internship count. Do NOT inflate. |
| "Years with [specific tool]" | `PROFILE_REQUIRED` | derived from `skill.<x>.years` if present else `0` | Missing → `0`, not blank, not guessed up. |
| Current company / title | `AUTO_SAFE` (may be blank) | `exp.current.*` or empty | Student → often blank or most recent internship. |
| LinkedIn URL | `PROFILE_REQUIRED` | `links.linkedin` | |
| Portfolio / GitHub | `AUTO_SAFE` | `links.github` | Optional. |
| Resume upload | `PROFILE_REQUIRED` | validated `resume_artifact` (see `RESUME_TRUTH_SYSTEM.md`) | Never upload an unvalidated artifact. |
| Cover letter | `HUMAN_REQUIRED` unless optional | generated + validated | Skip if the field is optional (cost). |

### Custom / screening questions
| Pattern | Class | Notes |
|---|---|---|
| Yes/No, maps to a known canonical question with ≥0.95 confidence | `PROFILE_REQUIRED` / `NEVER_GUESS` per topic | e.g. "18 or older?" → `AUTO_SAFE Yes`. |
| Single-select where every option can be mapped from a fact | `PROFILE_REQUIRED` | If no option matches the fact value → `HUMAN_REQUIRED` (`FORM_MAPPING`). |
| "How did you hear about us?" | `AUTO_SAFE` | constant `Company website` / `Job board`. |
| "Are you 18+ / legally able to be employed?" | `AUTO_SAFE` | `Yes`. |
| "Have you previously worked for / interned at [company]?" | `PROFILE_REQUIRED` | from `exp.*` history; default `No` only if history is complete. |
| "Do you have a non-compete?" | `AUTO_SAFE` | `No` (student). |
| Free-text essay ("Why do you want to work here?", "Describe a project…") | `HUMAN_REQUIRED` (v1) | Later: generate from validated facts + human approve. Never ship unreviewed. |
| Any question containing legal/authorization/citizenship/clearance terms | `NEVER_GUESS` | Route to human unless an exact canonical answer exists. |
| Question the classifier cannot categorize | `HUMAN_REQUIRED` | Fail closed. |

---

## 3. Recommended module shape (isolated helper, no conflict with Codex core)

```
app/applications/form_fields.py
  class FieldPolicy(StrEnum): AUTO_SAFE / PROFILE_REQUIRED / HUMAN_REQUIRED / NEVER_GUESS
  @dataclass FieldSpec: canonical_key: str; policy: FieldPolicy; fact_id: str|None; constant: str|None
  FIELD_SPECS: dict[str, FieldSpec]              # keyed by canonical field name
  def classify_label(raw_label: str, options: list[str]|None) -> FieldSpec | None
  def resolve_value(spec: FieldSpec, profile, answer_bank) -> ResolveResult
        # -> {status: FILLED|HUMAN_REQUIRED|BLOCKED, value, reason}
```
`classify_label` = deterministic keyword/regex mapping first; unmatched → `HUMAN_REQUIRED`. An LLM
label-classifier may be added later but only as a *fallback*, and its output for any `NEVER_GUESS`
topic is still routed to human.

---

## 4. Test hooks

`tests/test_form_field_taxonomy.py` (to add when the module lands) must assert:
- every `NEVER_GUESS` field with no canonical answer → `HUMAN_REQUIRED`
- authorization questions with novel phrasing → `HUMAN_REQUIRED`
- `grad_date` in the future is filled, not omitted
- a required GPA field with no `gpa` fact → `HUMAN_REQUIRED`, never a number
- "years with Kafka" when no Kafka skill fact → `0`, never blank-guessed-up
- demographic fields default to decline
