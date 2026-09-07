# APPLICATION_FORM_ENGINE.md — Canonical Field Model for Browser Application Automation

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Status:** design for Phase 4. `real_submission_enabled` stays `false`.
Supersedes nothing in `FORM_FIELD_TAXONOMY.md` — that doc is the policy table; this doc is the
**engine** design (data model + resolution algorithm + adapter contract) Codex builds to.

---

## 1. Fill-policy classes (5)

| Class | Definition | Engine behavior |
|---|---|---|
| `AUTO_SAFE` | Non-sensitive, constant or trivially derived. | Fill; log value + source. |
| `PROFILE_REQUIRED` | Must come from a specific `fact_id`. Missing/`TODO` fact ⇒ blocked. | Fill from fact. Missing ⇒ `HUMAN_REQUIRED` (`PROFILE_INCOMPLETE`). |
| `HUMAN_REQUIRED` | Judgment / free-text / knockout / anything not deterministically answerable. | Do not fill. Emit `human_task` with verbatim label + options + screenshot. |
| `NEVER_GUESS` | Legal / work-authorization / demographic. Wrong or fabricated = integrity violation. | Fill ONLY from an explicit human-authored canonical answer (`application_answers.*` or a `literal_only` fact). Any ambiguity, novel phrasing, missing canonical answer ⇒ `HUMAN_REQUIRED`. Never infer, never default (except the documented demographic "decline"). |
| `OPTIONAL_SKIP` | Field is optional AND we have no value AND it adds no application value. | Leave blank; record `skipped_optional`. |

Precedence when a label matches two classes: `NEVER_GUESS` > `HUMAN_REQUIRED` > `PROFILE_REQUIRED` >
`OPTIONAL_SKIP` > `AUTO_SAFE`.

---

## 2. Canonical field model

```python
class FieldGroup(StrEnum):
    PERSONAL = "personal"; EDUCATION = "education"; EXPERIENCE = "experience"
    APPLICATION = "application"; WORK_AUTH = "work_authorization"; LOCATION = "location"
    COMPENSATION = "compensation"; DEMOGRAPHIC = "demographic"; CUSTOM = "custom"

class InputKind(StrEnum):
    TEXT="text"; LONG_TEXT="long_text"; NUMERIC="numeric"; DATE="date"
    BOOL="bool"; SELECT="select"; MULTI_SELECT="multi_select"; FILE="file"

@dataclass(frozen=True)
class CanonicalField:
    key: str                       # stable, e.g. "personal.email"
    group: FieldGroup
    kind: InputKind
    policy: FieldPolicy
    fact_id: str | None            # for PROFILE_REQUIRED / literal_only
    answer_key: str | None         # for NEVER_GUESS -> application_answers.<key>
    constant: str | None           # for AUTO_SAFE
    derive: str | None             # name of a deterministic derivation fn
    required_by_default: bool       # hint; real requiredness is detected per form
    legal_sensitive: bool          # True => extra audit + never cached across candidates
```

### 2.1 PERSONAL
| key | kind | policy | source |
|---|---|---|---|
| `personal.first_name` | TEXT | PROFILE_REQUIRED | derive `split(name.full)` |
| `personal.middle_name` | TEXT | OPTIONAL_SKIP | `name.middle` if present |
| `personal.last_name` | TEXT | PROFILE_REQUIRED | derive `split(name.full)` |
| `personal.preferred_name` | TEXT | OPTIONAL_SKIP | `name.preferred` |
| `personal.email` | TEXT | PROFILE_REQUIRED | `contact.email` (the mailbox verification polls) |
| `personal.phone` | TEXT | PROFILE_REQUIRED | `contact.phone` — derive E.164 / `(xxx) xxx-xxxx` per form |
| `personal.address_line1` | TEXT | PROFILE_REQUIRED | `contact.address.line1` |
| `personal.address_line2` | TEXT | OPTIONAL_SKIP | `contact.address.line2` |
| `personal.city` | TEXT | PROFILE_REQUIRED | `contact.address.city` |
| `personal.state` | SELECT | PROFILE_REQUIRED | `contact.address.state` — map to option set |
| `personal.postal` | TEXT | PROFILE_REQUIRED | `contact.address.postal` |
| `personal.country` | SELECT | AUTO_SAFE | constant `United States` |

### 2.2 EDUCATION (repeatable; primary entry from `edu.primary.*`)
| key | kind | policy | notes |
|---|---|---|---|
| `education.institution` | TEXT/SELECT | PROFILE_REQUIRED | fuzzy-match typeahead; no match ⇒ HUMAN_REQUIRED (`FORM_MAPPING`) |
| `education.degree` | SELECT | PROFILE_REQUIRED | map `Bachelor's` etc. |
| `education.major` | TEXT | PROFILE_REQUIRED | |
| `education.minor` | TEXT | OPTIONAL_SKIP | |
| `education.gpa` | NUMERIC | PROFILE_REQUIRED **iff form-required**, else OPTIONAL_SKIP | missing + required ⇒ HUMAN_REQUIRED. **Never invent, never round up.** |
| `education.grad_month` | SELECT | PROFILE_REQUIRED | from `edu.primary.grad_date` |
| `education.grad_year` | SELECT | PROFILE_REQUIRED | future year is expected — never omit to look already-graduated |
| `education.start_date` | DATE | OPTIONAL_SKIP unless required | `edu.primary.start_date` |
| `education.currently_enrolled` | BOOL | AUTO_SAFE | derive from dates |

### 2.3 EXPERIENCE (repeatable from `exp.*`; may be empty for a student)
| key | kind | policy | notes |
|---|---|---|---|
| `experience.employer` | TEXT | PROFILE_REQUIRED per entry | literal from `exp.<n>.employer` |
| `experience.title` | TEXT | PROFILE_REQUIRED per entry | literal |
| `experience.start_date` / `experience.end_date` | DATE | PROFILE_REQUIRED per entry | literal |
| `experience.current_role` | BOOL | AUTO_SAFE | derive |
| `experience.description` | LONG_TEXT | HUMAN_REQUIRED (v1) | later: generated from validated facts + human approve |
| `experience.reason_for_leaving` | TEXT | HUMAN_REQUIRED | |

### 2.4 APPLICATION
| key | kind | policy | notes |
|---|---|---|---|
| `application.resume` | FILE | PROFILE_REQUIRED | validated `resume_artifact` only (`RESUME_TRUTH_SYSTEM.md`); never an unvalidated PDF |
| `application.cover_letter` | FILE/LONG_TEXT | HUMAN_REQUIRED unless field is optional | optional ⇒ OPTIONAL_SKIP (cost) |
| `application.portfolio_url` | TEXT | OPTIONAL_SKIP | `links.portfolio` |
| `application.linkedin_url` | TEXT | PROFILE_REQUIRED if present else OPTIONAL_SKIP | `links.linkedin` |
| `application.github_url` | TEXT | OPTIONAL_SKIP | `links.github` |
| `application.website_url` | TEXT | OPTIONAL_SKIP | `links.website` |

### 2.5 WORK_AUTHORIZATION — every row `NEVER_GUESS`, `legal_sensitive: true`
| key | kind | answer_key | canonical value (human-set) |
|---|---|---|---|
| `work_auth.authorized_us` | BOOL/SELECT | `work_authorized_us` | typically `Yes` (F-1 CPT/OPT) — **human-set fact, never inferred** |
| `work_auth.future_sponsorship` | BOOL/SELECT | `requires_sponsorship_now_or_future` | `Yes` |
| `work_auth.current_sponsorship` | BOOL/SELECT | `requires_sponsorship_now` | often `No` on CPT/OPT — human-set |
| `work_auth.visa_status` | SELECT/TEXT | `visa_status` | e.g. `F-1` — from a `literal_only` fact; free-text variant ⇒ HUMAN_REQUIRED |
| `work_auth.citizen_or_pr` | BOOL/SELECT | `us_citizen_or_pr` | usually `No` |
| `work_auth.*` free-text ("describe your status") | LONG_TEXT | — | **always HUMAN_REQUIRED** |
| any auth label the classifier maps < 0.95 | — | — | **HUMAN_REQUIRED** |

### 2.6 LOCATION
| key | kind | policy | notes |
|---|---|---|---|
| `location.relocation` | BOOL/SELECT | PROFILE_REQUIRED | `application_answers.willing_to_relocate` |
| `location.relocation_specific_city` | BOOL | HUMAN_REQUIRED unless answer is unconditional yes | |
| `location.remote_ok` / `location.hybrid_ok` / `location.onsite_ok` | BOOL | PROFILE_REQUIRED | `application_answers.work_mode_pref` |
| `location.preferred_location` | TEXT | PROFILE_REQUIRED | derived `city, state` |

### 2.7 COMPENSATION
| key | kind | policy | notes |
|---|---|---|---|
| `compensation.salary_expectation` | NUMERIC | PROFILE_REQUIRED | `comp.target_base`; missing + required ⇒ HUMAN_REQUIRED |
| `compensation.salary_expectation_text` | TEXT | HUMAN_REQUIRED | free text / ranges / "negotiable" |
| `compensation.hourly_expectation` | NUMERIC | HUMAN_REQUIRED | usually out of scope |
| `compensation.knockout_threshold` ("is $X acceptable?") | BOOL | HUMAN_REQUIRED | wrong answer auto-rejects or misrepresents |

### 2.8 DEMOGRAPHIC / OPTIONAL — every row `NEVER_GUESS`, default **decline**
| key | default | override only if |
|---|---|---|
| `demographic.gender` | `Decline to self-identify` | `application_answers.eeo_gender` explicitly set |
| `demographic.race_ethnicity` | `Decline to self-identify` | explicit |
| `demographic.veteran_status` | `I don't wish to answer` | explicit |
| `demographic.disability_status` | `I don't wish to answer` | explicit |
| `demographic.hispanic_latino` | `Decline` | explicit |
| `demographic.pronouns` | OPTIONAL_SKIP | `application_answers.pronouns` set — never from name |

### 2.9 CUSTOM (by input kind)
| kind | default policy | escalation |
|---|---|---|
| BOOL (yes/no) | classify → known canonical ⇒ its policy; else HUMAN_REQUIRED | "18+?" ⇒ AUTO_SAFE `Yes`; "worked here before?" ⇒ PROFILE_REQUIRED from `exp.*` |
| SELECT | PROFILE_REQUIRED if every option maps from a fact | no option matches ⇒ HUMAN_REQUIRED (`FORM_MAPPING`) |
| MULTI_SELECT | PROFILE_REQUIRED if fully mappable | else HUMAN_REQUIRED |
| NUMERIC | PROFILE_REQUIRED if a numeric fact exists (`0` is a valid answer) | "years with X" & no fact ⇒ `0`, never blank-guessed-up |
| DATE | PROFILE_REQUIRED (e.g. earliest start = grad_date + buffer) | ambiguous ⇒ HUMAN_REQUIRED |
| TEXT (short) | HUMAN_REQUIRED unless it maps to a canonical answer | "how did you hear about us?" ⇒ AUTO_SAFE `Company website` |
| LONG_TEXT (essay) | HUMAN_REQUIRED (v1) | later: generate from validated facts + human approve |
| FILE | PROFILE_REQUIRED (resume) / OPTIONAL_SKIP | non-resume uploads optional |
| any label containing legal/authorization/citizenship/clearance/visa/sponsorship terms | NEVER_GUESS | route to human unless exact canonical answer exists |

---

## 3. Resolution algorithm

```
resolve(form_field) -> ResolveResult{status, value, policy, source, confidence, reason}

1. label + options + surrounding text  ->  classify_label()  -> CanonicalField | None
      deterministic keyword/regex map FIRST.
      LLM label classifier only as a FALLBACK, and its output for any NEVER_GUESS
      topic is still forced to HUMAN_REQUIRED.
2. detect requiredness from the live DOM (aria-required, *, "required", validation on blur).
3. switch on field.policy:
   AUTO_SAFE        -> value = constant/derive();          status=FILLED
   PROFILE_REQUIRED -> fact = profile.get(field.fact_id)
                       fact missing/TODO -> status=BLOCKED  reason=PROFILE_INCOMPLETE
                       else map to option set; unmappable -> status=HUMAN_REQUIRED (FORM_MAPPING)
                       else status=FILLED
   NEVER_GUESS      -> ans = answer_bank.get(field.answer_key) (or literal_only fact)
                       ambiguous label OR missing ans -> status=HUMAN_REQUIRED
                       else status=FILLED  (log verbatim, audit)
   HUMAN_REQUIRED   -> status=HUMAN_REQUIRED
   OPTIONAL_SKIP    -> if required-by-form -> re-resolve as PROFILE_REQUIRED
                       else status=SKIPPED
4. every FILLED writes an entry to the dry-run transcript (DRY_RUN_DESIGN.md):
   {label, canonical_key, value, policy, source_fact_id/answer_key, confidence}
5. any BLOCKED or HUMAN_REQUIRED -> application -> HUMAN_REQUIRED + human_task; do NOT submit.
```

Confidence values: `AUTO_SAFE`, `PROFILE`, `MAPPED` (fuzzy option match ≥ threshold), `HUMAN_REQUIRED`.
A form with **any** required field not `FILLED` is never submitted.

---

## 4. Adapter contract additions

```python
class FormAdapter(Protocol):
    def locate_form(self, page) -> FormHandle: ...
    def enumerate_fields(self, form) -> list[RawFormField]:   # label, kind, options, required, selector
        ...
    def set_value(self, field: RawFormField, value: str) -> None: ...
    def upload_file(self, field: RawFormField, path: str) -> None: ...
    def read_validation_errors(self, form) -> list[str]: ...
    def find_submit(self, form) -> ElementHandle | None: ...
    def is_captcha_present(self, page) -> bool: ...      # True -> HUMAN_REQUIRED, never solve
```

- `enumerate_fields` uses role/label locators, not brittle CSS.
- `set_value` re-reads the field after setting (parsers overwrite — Workday especially) and diffs vs
  intended; mismatch ⇒ retry once then `FORM_MAPPING` → HUMAN_REQUIRED.
- CAPTCHA/MFA/verification-email detection short-circuits to HUMAN_REQUIRED with a screenshot.

---

## 5. Tests to add when the engine lands

`tests/test_form_engine.py`:
- every `NEVER_GUESS` field with no canonical answer ⇒ HUMAN_REQUIRED
- authorization label with novel phrasing ⇒ HUMAN_REQUIRED (never FILLED)
- future `grad_year` ⇒ FILLED (not omitted)
- required GPA field, no `gpa` fact ⇒ HUMAN_REQUIRED, never a number
- "years with Kafka", no Kafka fact ⇒ `0`
- demographic fields ⇒ decline default
- SELECT with no mappable option ⇒ HUMAN_REQUIRED
- any BLOCKED/HUMAN_REQUIRED field ⇒ workflow never calls `submit()`
