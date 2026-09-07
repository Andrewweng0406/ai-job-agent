SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    career_url TEXT NOT NULL,
    ats_type TEXT,
    ats_identifier TEXT,
    industry TEXT,
    last_crawled_at TEXT,
    crawl_status TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_job_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    job_family TEXT NOT NULL,
    location TEXT NOT NULL,
    remote_status TEXT,
    employment_type TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    currency TEXT NOT NULL,
    description TEXT NOT NULL,
    requirements_json TEXT NOT NULL DEFAULT '[]',
    preferred_qualifications_json TEXT NOT NULL DEFAULT '[]',
    posted_at TEXT,
    discovered_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    apply_url TEXT NOT NULL,
    ats_type TEXT NOT NULL,
    description_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_data_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source, external_job_id)
);

CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    job_id INTEGER NOT NULL,
    company TEXT NOT NULL,
    position TEXT NOT NULL,
    location TEXT NOT NULL,
    job_family TEXT NOT NULL,
    source TEXT NOT NULL,
    ats_type TEXT NOT NULL,
    match_score REAL,
    persona TEXT,
    resume_id TEXT,
    discovered_at TEXT,
    queued_at TEXT,
    applied_at TEXT,
    submission_verified_at TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    worker_id TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    lease_epoch INTEGER NOT NULL DEFAULT 0,
    failure_category TEXT,
    failure_reason TEXT,
    human_required_reason TEXT,
    confirmation_data_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id),
    UNIQUE(job_id)
);

CREATE TABLE IF NOT EXISTS application_state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(application_id) REFERENCES applications(application_id)
);

CREATE TABLE IF NOT EXISTS job_filter_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    allowed INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS resumes (
    resume_id TEXT PRIMARY KEY,
    job_id INTEGER NOT NULL,
    persona TEXT NOT NULL,
    base_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '{}',
    validation_status TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS human_tasks (
    task_id TEXT PRIMARY KEY,
    application_id TEXT,
    job_id INTEGER,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    blocking_state TEXT NOT NULL,
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',
    context_json TEXT NOT NULL DEFAULT '{}',
    resume_token TEXT,
    resolution_json TEXT,
    resolved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(application_id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_human_tasks_status ON human_tasks(status, category);
CREATE INDEX IF NOT EXISTS idx_human_tasks_app ON human_tasks(application_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_human_tasks_open_unique
ON human_tasks(application_id, category)
WHERE status IN ('OPEN', 'IN_PROGRESS');

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status, queued_at);
CREATE INDEX IF NOT EXISTS idx_transitions_app ON application_state_transitions(application_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_company_status ON jobs(company_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_incremental ON jobs(source, external_job_id, description_hash, status);
CREATE INDEX IF NOT EXISTS idx_jobs_source_company ON jobs(source, company_id);

CREATE TABLE IF NOT EXISTS dry_run_transcripts (
    transcript_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    job_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    would_submit INTEGER NOT NULL,
    blocking_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(application_id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_dryrun_app ON dry_run_transcripts(application_id, created_at);
"""
