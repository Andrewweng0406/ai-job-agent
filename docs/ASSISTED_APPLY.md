# Assisted Apply — human-in-the-loop submission

The agent never submits. It prepares each application to a fully-reviewable state;
**you** click Submit.

## Flow

### 1. Generate a review packet

```
python3 scripts/assisted_apply.py packet \
  --url "https://boards.greenhouse.io/<org>/jobs/<id>" \
  --company "<Company>" --ats greenhouse \
  --profile config/candidate_profile.local.yaml \
  --resume-pdf path/to/your_resume.pdf \
  --out review/<slug>
```

Writes `review/<slug>/`:

| file | what |
|---|---|
| `packet.md` / `packet.json` | the review packet |
| `field_selectors.json` | maps each `qN` to its DOM selector (used by `fill`) |
| `before_fill.png` | the empty form |
| `dom.sanitized.html` | sanitized DOM snapshot |

The packet has two lists:

- **Pre-fill from your profile** — name, email, phone, school, LinkedIn, EEO
  ("Decline to self-identify"), work authorization. Shown as masked hints, never
  raw values.
- **You must answer** — every required question with no profile mapping
  (country, degree/dates, sponsorship, conflict-of-interest disclosures, "why
  this company", …). The agent will not write these.

`review/` is gitignored — packets contain your real answers.

### 2. Write your answers

Create `review/<slug>/answers.yaml`:

```yaml
approved_by: andrew
approved_at: 2026-09-08T10:30:00-07:00
answers:
  q3: "United States"
  q8: "Bachelor's Degree"
  q9: "May"
  q10: "2027"
  q13: "Yes"
  q14: "No"
  # ... one entry for every qN in packet.md
```

`fill` refuses to run unless **every required** `qN` has a non-empty answer and
the approval fields are present and valid. Option-constrained answers (selects)
are checked against the form's allowed values.

### 3. Assisted fill — you submit

```
python3 scripts/assisted_apply.py fill --packet review/<slug> --headed \
  --profile config/candidate_profile.local.yaml --resume-pdf path/to/your_resume.pdf
```

`--headed` opens a visible browser, fills the safe fields + your answers, screenshots
`after_fill.png`, and stops with the browser open. **Review the form yourself and
click Submit.** Press Enter in the terminal to close the browser afterward.

There is no code path in this tool that submits: no click on a submit control, no
`requestSubmit`, no Enter key, no adapter with submission enabled.

## Safety properties

- Only `FILLED` resolutions (deterministic profile facts) are auto-typed; anything
  the resolver is unsure about becomes a question for you.
- `NEVER_GUESS` / legal-sensitive fields are never auto-filled and never shown with
  a raw value.
- A `BLOCKED` field (e.g. resume failed validation) makes the packet not-ready and
  `fill` refuses.
- `real_submission_enabled` stays `false` everywhere.
