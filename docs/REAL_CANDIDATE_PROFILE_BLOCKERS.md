# Real Candidate Profile Blockers

The application profile is intentionally fail-closed while required candidate facts remain `TODO`.

`meta.candidate_id` is an internal database namespace, not a candidate fact. If
it remains `TODO`, the loader assigns a stable internal UUID automatically. This
does not unlock any profile field, create identity data, or authorize autofill.
These values must be supplied by the candidate before an approved live autofill dry-run can be
performed. Synthetic values must never be copied into this file or accepted by a real submission path.

Required facts currently missing: none.

The candidate confirmed their name as the canonical identity for the supplied resume and LinkedIn
profile. Contact data and the completed local profile are intentionally local-only and are not committed
to the public repository. The profile still never authorizes submission: `would_submit=false` and real
submission remains disabled.
