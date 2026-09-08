"""Read-only probe: for each candidate org slug, try the public Greenhouse / Lever / Ashby
job-board endpoints and report which resolve, with a live job count. Emits YAML registry
entries for the ones that work. No writes, no auth, no submission.

Usage: python3 scripts/probe_ats_boards.py [--emit]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

UA = "ai-job-agent-probe/0.1 (read-only board verification)"
TIMEOUT = 20

# (company_id, company_name, industry, [candidate slugs to try])
CANDIDATES = [
    ("airbnb", "Airbnb", "Travel", ["airbnb"]),
    ("gitlab", "GitLab", "Developer Tools", ["gitlab"]),
    ("coinbase", "Coinbase", "Crypto", ["coinbase"]),
    ("robinhood", "Robinhood", "Financial Technology", ["robinhood"]),
    ("discord", "Discord", "Consumer", ["discord"]),
    ("dropbox", "Dropbox", "Productivity", ["dropbox"]),
    ("doordash", "DoorDash", "Delivery", ["doordash"]),
    ("instacart", "Instacart", "Delivery", ["instacart", "maplebear"]),
    ("plaid", "Plaid", "Financial Technology", ["plaid"]),
    ("brex", "Brex", "Financial Technology", ["brex"]),
    ("ramp", "Ramp", "Financial Technology", ["ramp"]),
    ("gusto", "Gusto", "HR Tech", ["gusto"]),
    ("samsara", "Samsara", "IoT", ["samsara"]),
    ("benchling", "Benchling", "Biotech", ["benchling"]),
    ("figma", "Figma", "Design", ["figma"]),
    ("notion", "Notion", "Productivity", ["notion"]),
    ("retool", "Retool", "Developer Tools", ["retool"]),
    ("scaleai", "Scale AI", "AI", ["scaleai", "scale-ai", "scale"]),
    ("affirm", "Affirm", "Financial Technology", ["affirm"]),
    ("chime", "Chime", "Financial Technology", ["chime"]),
    ("sofi", "SoFi", "Financial Technology", ["sofi"]),
    ("cloudflare", "Cloudflare", "Infrastructure", ["cloudflare"]),
    ("reddit", "Reddit", "Consumer", ["reddit"]),
    ("pinterest", "Pinterest", "Consumer", ["pinterest"]),
    ("snowflake", "Snowflake", "Data", ["snowflake"]),
    ("datadog", "Datadog", "Observability", ["datadog"]),
    ("hashicorp", "HashiCorp", "Infrastructure", ["hashicorp"]),
    ("twilio", "Twilio", "Communications", ["twilio"]),
    ("asana", "Asana", "Productivity", ["asana"]),
    ("lyft", "Lyft", "Transportation", ["lyft"]),
    ("nerdwallet", "NerdWallet", "Financial Technology", ["nerdwallet"]),
    ("wealthsimple", "Wealthsimple", "Financial Technology", ["wealthsimple"]),
    ("faire", "Faire", "Marketplace", ["faire"]),
    ("verkada", "Verkada", "Security", ["verkada"]),
    ("rippling", "Rippling", "HR Tech", ["rippling"]),
    ("deel", "Deel", "HR Tech", ["deel"]),
    ("airtable", "Airtable", "Productivity", ["airtable"]),
    ("webflow", "Webflow", "Design", ["webflow"]),
    ("vercel", "Vercel", "Developer Tools", ["vercel"]),
    ("linear", "Linear", "Developer Tools", ["linear"]),
    ("mistral", "Mistral AI", "AI", ["mistralai", "mistral"]),
    ("perplexity", "Perplexity AI", "AI", ["perplexityai", "perplexity-ai", "perplexity"]),
    ("anduril", "Anduril", "Defense", ["anduril"]),
    ("palantir", "Palantir", "Data", ["palantir"]),
    ("nvidia", "NVIDIA", "Semiconductors", ["nvidia"]),
]


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def try_greenhouse(slug: str):
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if isinstance(jobs, list) and jobs:
        return "greenhouse", slug, len(jobs)
    return None


def try_lever(slug: str):
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if isinstance(data, list) and data:
        return "lever", slug, len(data)
    return None


def try_ashby(slug: str):
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if isinstance(jobs, list) and jobs:
        return "ashby", slug, len(jobs)
    return None


PROBES = [try_greenhouse, try_lever, try_ashby]


def main() -> int:
    emit = "--emit" in sys.argv
    verified = []
    for company_id, name, industry, slugs in CANDIDATES:
        hit = None
        for slug in slugs:
            for probe in PROBES:
                try:
                    result = probe(slug)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                        json.JSONDecodeError, ValueError):
                    result = None
                time.sleep(0.15)
                if result:
                    hit = result
                    break
            if hit:
                break
        if hit:
            ats, slug, count = hit
            verified.append((company_id, name, industry, ats, slug, count))
            print(f"  OK  {name:<16} {ats:<11} {slug:<18} {count} jobs")
        else:
            print(f"  --  {name:<16} (no public greenhouse/lever/ashby board)")

    print(f"\n{len(verified)} verified boards\n")
    if emit:
        base = {"greenhouse": "https://job-boards.greenhouse.io/",
                "lever": "https://jobs.lever.co/",
                "ashby": "https://jobs.ashbyhq.com/"}
        status = {"greenhouse": "verified_public_greenhouse_board",
                  "lever": "verified_public_lever_board",
                  "ashby": "verified_public_ashby_board"}
        for company_id, name, industry, ats, slug, count in verified:
            print(f"""  - company_id: {company_id}
    company_name: {name}
    career_url: {base[ats]}{slug}
    ats_type: {ats}
    ats_identifier: {slug}
    active: true
    industry: {industry}
    metadata:
      discovery_status: {status[ats]}
      probe_job_count: {count}""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
