from __future__ import annotations

from app.applications.ats_dom_dry_run import AtsDomDryRunAdapter, AtsDomDryRunResult


AshbyDryRunResult = AtsDomDryRunResult


class AshbyDryRunAdapter(AtsDomDryRunAdapter):
    def __init__(self, repository, real_submission_enabled: bool = False) -> None:
        super().__init__(repository, ats_type="ashby", real_submission_enabled=real_submission_enabled)
