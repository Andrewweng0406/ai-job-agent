# Real Candidate Profile Blockers

The application profile is intentionally fail-closed while required candidate facts remain `TODO`.

`meta.candidate_id` is an internal database namespace, not a candidate fact. If
it remains `TODO`, the loader assigns a stable internal UUID automatically. This
does not unlock any profile field, create identity data, or authorize autofill.
These values must be supplied by the candidate before an approved live autofill dry-run can be
performed. Synthetic values must never be copied into this file or accepted by a real submission path.

Required facts currently missing: none.

Resume-derived identity, education, skills, projects, and experience are now present locally. Contact
data is intentionally local-only and is not committed to the public repository. The LinkedIn URL uses
a different display-name slug than the resume and therefore requires human identity confirmation before
autofill. The profile still never authorizes submission: `would_submit=false` and real submission remains disabled.
