from __future__ import annotations

from app.models.job import Job, stable_hash
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_NAMES = {"gh_src", "lever-source", "src", "source", "ref", "referrer"}
LEGAL_SUFFIX_PATTERN = re.compile(r"\b(inc|inc\.|llc|ltd|corp|corporation|co|company)\b", re.I)
TITLE_LEVEL_PATTERN = re.compile(r"\b(i|ii|iii|iv|1|2|3)\b$", re.I)
STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "of",
    "the",
    "to",
    "with",
    "you",
    "will",
    "posted",
    "viewed",
    "times",
}


def job_identity_keys(job: Job) -> set[str]:
    canonical_url = canonicalize_url(job.apply_url)
    req_id = _extract_req_id(canonical_url)
    keys = {
        f"external:{job.source}:{job.external_job_id}",
        f"apply_url:{stable_hash(canonical_url)}",
        f"company_title_location:{stable_hash('|'.join([_normalize_company(job.company_name), _normalize_title(job.normalized_title or job.title), _normalize_location(job.location)]))}",
    }
    if req_id:
        keys.add(f"req_title_location:{stable_hash('|'.join([req_id, _normalize_title(job.title), _normalize_location(job.location)]))}")
        keys.add(f"req_company:{stable_hash('|'.join([req_id, _normalize_company(job.company_name)]))}")
    if job.description_hash:
        keys.add(f"description:{job.description_hash}")
    keys.update(_description_shingle_keys(job.description))
    return keys


def strong_job_identity_keys(job: Job) -> set[str]:
    """Keys safe for a global seen-set; excludes boilerplate-prone shingles."""
    return {key for key in job_identity_keys(job) if not key.startswith("description_shingle:")}


def is_duplicate(job: Job, seen_keys: set[str]) -> bool:
    return bool(job_identity_keys(job) & seen_keys)


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in TRACKING_QUERY_NAMES and not key.startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(query), ""))


def _extract_req_id(url: str) -> str | None:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    for key in ("gh_jid", "job_id", "jobId", "requisition_id", "requisitionId"):
        value = query.get(key)
        if value and re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            return value.lower()
    matches = re.findall(r"(?:jobs?|postings?|requisitions?)/([a-zA-Z0-9_-]+)", url)
    if matches:
        candidate = matches[-1].lower()
        if candidate not in {"search", "results", "view", "apply", "openings"}:
            return candidate
    numeric = re.findall(r"\b\d{3,}\b", url)
    return numeric[-1] if numeric else None


def _normalize_company(value: str) -> str:
    cleaned = LEGAL_SUFFIX_PATTERN.sub("", value.lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", cleaned).split())


def _normalize_title(value: str) -> str:
    cleaned = TITLE_LEVEL_PATTERN.sub("", value.lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", cleaned).split())


def _normalize_location(value: str) -> str:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    return {
        "new york ny": "new york",
        "nyc": "new york",
        "san francisco ca": "san francisco",
    }.get(normalized, normalized)


def _description_shingle_keys(description: str) -> set[str]:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", description.lower())
        if token not in STOPWORDS and not token.isdigit() and not re.fullmatch(r"20\d{2}", token)
    ]
    keys = set()
    for index in range(max(0, len(tokens) - 2)):
        keys.add(f"description_shingle:{stable_hash(' '.join(tokens[index:index + 3]))}")
    return keys
