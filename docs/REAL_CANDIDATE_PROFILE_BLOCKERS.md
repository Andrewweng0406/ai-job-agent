# Real Candidate Profile Blockers

The application profile is intentionally fail-closed while required candidate facts remain `TODO`.

`meta.candidate_id` is an internal database namespace, not a candidate fact. If
it remains `TODO`, the loader assigns a stable internal UUID automatically. This
does not unlock any profile field, create identity data, or authorize autofill.
These values must be supplied by the candidate before an approved live autofill dry-run can be
performed. Synthetic values must never be copied into this file or accepted by a real submission path.

Required facts currently missing:

- `meta.candidate_id`
- `name.full`
- `personal_information.email`
- `personal_information.phone`
- `edu.primary.school`
- `edu.primary.degree`
- `edu.primary.grad_date`
- `auth.status`
- `auth.needs_future_sponsorship`

The legacy profile fields for location, work authorization, sponsorship, education, skills, projects,
experience, and application answers also remain incomplete. Until the profile is completed and the
resume artifact passes PDF QA, the system must route unresolved fields to `HUMAN_REQUIRED`, keep
`would_submit=false`, and avoid resume upload or submission.
