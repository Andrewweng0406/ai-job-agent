# Third-Party Notices

This file records open-source repositories inspected as authorized engineering
references. No source code was copied or substantially adapted into this
repository; the local implementations are clean reimplementations.

| Upstream repository | Upstream files reviewed | Commit | License | Local destination | Treatment |
|---|---|---|---|---|---|
| https://github.com/idea-torx/CareerWeaver | `docs/agents.md`, `src/weaver/preflight.py`, `tests/test_stepwise.py`, `lever-and-upload-verify-contract.md` | `34068a1efe8eb8fcf33c51b5e9fa42d1205cd72d` | MIT, `LICENSE` (Copyright (c) 2026 Leo Felix and contributors) | `docs/OPEN_SOURCE_REFERENCE_COMPARISON.md`; existing application/evidence modules | Concepts reimplemented; no code copied |
| https://github.com/muhammad-saadd/applyai | `content_scripts/greenhouse.js`, `content_scripts/lever.js`, `content_scripts/ashby.js`, `content_scripts/utils/parser.js` | `d4a97b5643aa219592883a43b068fc18dff94678` | MIT, `LICENSE` (Copyright (c) 2026 Muhammad Saad) | `docs/OPEN_SOURCE_REFERENCE_COMPARISON.md`; existing shared HTML extractor | Concepts reimplemented; no code copied |
| https://github.com/AkbarDevop/ai-job-agent | `scripts/greenhouse-apply.js`, `scripts/lever-apply.js`, `scripts/ashby-apply.js`, `scripts/parse-resume.mjs`, `skills/job-track/SKILL.md`, `scripts/tracker-status-update.py` | `9ce47d29b5fcfd37ea2fdd5588c8d178bbfa7305` | MIT, `LICENSE` (Copyright (c) 2026 Akbarjon Kamoldinov) | `docs/OPEN_SOURCE_REFERENCE_COMPARISON.md`; existing ledger/resume modules | Concepts reimplemented; no code copied |

The MIT license texts remain in their respective upstream repositories because
no upstream code is distributed here. If a future change copies or
substantially adapts a file, this table must be updated with the exact file,
commit, notice, and local destination before merging.
