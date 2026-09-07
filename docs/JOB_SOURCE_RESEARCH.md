# JOB_SOURCE_RESEARCH.md — Job Discovery Sources

**Author:** Claude (reviewer / independent research)
**Updated:** 2026-09-06
**Goal:** discover a large, fresh volume of U.S. new-grad postings from official/structured sources.

> Scope rule: only public, documented, or openly-served endpoints. No CAPTCHA/auth/anti-bot bypass.
> Every endpoint below must be re-verified against live responses before adapter code depends on it;
> ATS vendors change paths and pagination without notice.

---

## 1. Summary ranking

| Rank | Source | Why | Discovery method | Structured endpoint | Effort |
|---|---|---|---|---|---|
| 1 | **Greenhouse** | Huge new-grad/tech footprint, clean public JSON, stable numeric IDs | per-company board token | Yes (Job Board API) | Low |
| 2 | **Lever** | Common at mid-size tech, clean public JSON | per-company handle | Yes (`/v0/postings`) | Low |
| 3 | **Ashby** | Fast-growing, well-formed public job-board API, comp data | per-org slug | Yes (Posting API) | Low |
| 4 | **Workday (myworkdayjobs)** | Dominates F500 / large employers → most "new grad" programs | per-tenant + site path | Yes (undoc. CXS JSON) | Medium |
| 5 | **SmartRecruiters** | Public posting API, many enterprises | per-company id | Yes (`posting-api`) | Low |
| 6 | **Workable** | Many SMB/startups | per-account subdomain | Yes (`/spi/v3` / `apply` API) | Low |
| 7 | **iCIMS** | Large enterprise share | per-customer portal | Partial (HTML/JSON hybrid) | High |
| 8 | **Taleo / Oracle Cloud Recruiting** | Legacy enterprise | per-instance | Weak / brittle | High |
| 9 | **USAJOBS** | Federal roles, fully official API | national API + keyword | Yes (official, key) | Low (but citizenship filter) |
| 10 | Aggregator lists (SimplifyJobs, etc.) | Seed the **company registry**, not a live feed | GitHub JSON/README | Yes (repo files) | Low |

---

## 2. Per-source detail

### 2.1 Greenhouse
- **Discovery:** need the company's `board_token` (e.g. `stripe`, `airbnb`). No global list endpoint — build the registry from aggregator lists, `boards.greenhouse.io` link patterns on career pages, and known-company crawls.
- **Endpoints (public Job Board API, no auth):**
  - `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` — all postings + HTML description.
  - `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}` — single posting.
  - `GET https://boards-api.greenhouse.io/v1/boards/{token}/offices` / `/departments` — for filtering.
- **Stable ID:** numeric `id` per posting; also `internal_job_id` (groups multi-location listings). Use `internal_job_id` for near-dedupe, `id` for exact.
- **Normalization:** `location.name` is free text ("San Francisco, CA" / "Remote - US" / "US"); needs a location parser. Description is HTML. `updated_at` present — use for incremental.
- **Incremental:** poll per board; diff on `updated_at` and set of `id`s. Cheap (one request per board, often <100 KB).
- **Rate limits:** not officially published; be polite (≤1–2 req/s per IP overall, small concurrency). Honor 429 + `Retry-After`.
- **Limitations:** some boards disable the API/`content`; some use Greenhouse only for hosting and embed via JS. Fallback: `https://boards.greenhouse.io/embed/job_board?for={token}` (HTML).

### 2.2 Lever
- **Discovery:** per-company handle (e.g. `netflix`). Same registry approach.
- **Endpoint (public):** `GET https://api.lever.co/v0/postings/{company}?mode=json` (add `&group=team` etc.). Returns array of postings with `id` (UUID), `text` (title), `categories.location/team/commitment`, `descriptionPlain`, `lists` (responsibilities/requirements as structured bullets — useful), `applyUrl`, `createdAt`.
- **Stable ID:** UUID `id`. Persistent.
- **Incremental:** no server-side "changed since"; diff full list per company. `createdAt` only (no `updatedAt`), so detect edits via `content_hash`.
- **Rate limits:** undocumented; modest concurrency, honor 429.
- **Limitations:** newer Lever tenants may serve a different job-board API; verify. Some hide `descriptionPlain`.

### 2.3 Ashby
- **Discovery:** per-org job-board slug (e.g. `ramp`). Registry approach.
- **Endpoint (public Posting API):**
  - `POST https://api.ashbyhq.com/posting-api/job-board/{org}` with JSON body `{}` (or GET) → `jobPostings[]`.
  - Query params: `?includeCompensation=true`.
- **Stable ID:** `id` (UUID) per posting; `jobId` groups locations.
- **Normalization:** structured `locationName`, `employmentType`, `isRemote`, `compensation` (often present — good signal). Description in HTML.
- **Incremental:** `publishedDate` / diff; also `content_hash`.
- **Rate limits:** undocumented; polite.
- **Limitations:** smaller total universe than Greenhouse/Workday but high new-grad density (startups).

### 2.4 Workday (`*.myworkdayjobs.com`)
- **Why it matters most for this product:** the majority of large-employer "New Grad" / "University" / "Early Careers" programs (banks, insurers, big tech, retailers) run on Workday.
- **Discovery:** need tenant + site. URL shape: `https://{tenant}.wd{N}.myworkdayjobs.com/{lang}/{site}` (e.g. `nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite`). Build registry from career-page redirects.
- **Endpoint (undocumented but openly served JSON, no auth):**
  - `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`
    body: `{"appliedFacets":{}, "limit":20, "offset":0, "searchText":""}` → `{total, jobPostings:[{title, externalPath, locationsText, postedOn, bulletFields}]}`.
  - Detail: `GET https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}` → full JD, `jobRequisitionId`.
  - Facets endpoint gives location/category filters to narrow to US + entry level.
- **Stable ID:** `jobRequisitionId` (from detail) — the real key. `externalPath` contains a slug + id and is fairly stable.
- **Pagination:** `offset` in steps of `limit` (max 20). `total` provided.
- **Incremental:** `postedOn` is relative text ("Posted 3 Days Ago") in list — use detail `startDate`/`postedOn` ISO or `content_hash`. Diff requisition-id set per site.
- **Rate limits:** undocumented; Workday is sensitive — keep concurrency very low per tenant (1), add jitter, honor 429, cache aggressively.
- **Limitations:** every tenant can customize field names; `bulletFields` varies. Some tenants gate the CXS endpoint behind a session cookie from the HTML page first (GET the site, carry cookies). Never bypass a real bot check if one appears — mark and skip.

### 2.5 SmartRecruiters
- **Endpoint (public Posting API, no auth):** `GET https://api.smartrecruiters.com/v1/companies/{companyId}/postings?limit=100&offset=0` → `content[]` with `id`, `name`, `location`, `releasedDate`, `ref`. Detail: `.../postings/{id}` → full JD + `jobAd.sections`.
- **Stable ID:** `id` (UUID) + `refNumber`.
- **Incremental:** `releasedDate`; pagination by offset; `totalFound`.
- **Rate limits:** documented soft limits; polite concurrency fine.
- **Limitations:** `companyId` is the SR identifier (not always the brand name).

### 2.6 Workable
- **Endpoints:**
  - `GET https://apply.workable.com/api/v3/accounts/{account}/jobs` (POST with `{}` on some tenants) → published jobs.
  - Legacy: `GET https://{account}.workable.com/spi/v3/jobs`.
  - Widget JSON: `https://www.workable.com/api/accounts/{account}?details=true`.
- **Stable ID:** `shortcode` (e.g. `ABC123DEF0`) — stable, used in apply URL.
- **Incremental:** `published_on` / `created_at`; diff shortcodes.
- **Rate limits:** modest; honor 429.
- **Limitations:** many tiny accounts → registry noise; lots of non-US.

### 2.7 iCIMS
- **Discovery:** customer portal host (`careers-{customer}.icims.com` or `{customer}.icims.com`).
- **Structured access:** search results are server-rendered HTML with predictable pagination params (`?searchRelevanceKeyword=`, `&pr=` page). Some portals expose a JSON search; inconsistent.
- **Stable ID:** requisition id in the job URL (`/jobs/{id}/{slug}/job`).
- **Effort:** High — HTML parsing per template, brittle. Defer until top ATSes are covered.

### 2.8 Taleo / Oracle Cloud Recruiting (ORC)
- Legacy Taleo: `.../careersection/...` — heavy, session-based, brittle. ORC has a REST-ish `/hcmRestApi/resources/latest/recruitingCEJobRequisitions` on some tenants.
- **Effort:** High, low ROI per hour. Deprioritize.

### 2.9 USAJOBS (federal)
- **Official API:** `https://data.usajobs.gov/api/search` with `Authorization-Key` header (free key) + `User-Agent: your-email`. Fully documented, keyword + location + grade filters, stable `MatchedObjectId` (control number).
- **Caveat:** most federal roles require U.S. citizenship — filter hard on `JobCategory`/`PositionSchedule` and the "who may apply" field; likely a small slice for an international candidate. Include but expect low yield.

### 2.10 Aggregator / curated lists (registry seeds, not live sources)
- GitHub new-grad roundups (e.g. SimplifyJobs/New-Grad-Positions and similar) publish structured `listings.json` with company, role, URL, date, and often the ATS. Use to **seed and refresh the company registry** and cross-check freshness. Respect each repo's license; treat as a hint, always re-fetch the canonical ATS posting.
- levels.fyi / company career indexes: manual registry additions.
- Do **not** scrape LinkedIn/Indeed/Glassdoor job pages — ToS + anti-bot; if used at all, only their official/partner APIs.

---

## 3. Company Registry (the core asset)

Schema:
```
companies(
  id, canonical_name, aliases[], careers_url,
  ats_provider ENUM, ats_token,            -- board_token / handle / tenant+site / companyId
  ats_extra JSONB,                         -- wd shard, site path, lang
  us_hiring BOOL, new_grad_program BOOL,
  status ENUM(active, empty, dead, blocked),
  last_crawl_at, last_success_at, consecutive_empty INT,
  added_by, added_reason, verified_at
)
```
- **Bootstrapping:** seed 800–1500 companies from aggregator lists + a curated F500/tech list, then run a one-time "resolve ATS" crawl: fetch `careers_url`, follow redirects, detect provider by host/DOM markers, extract token.
- **Health:** mark `dead` after M consecutive empty/404 crawls; re-check monthly.
- **Growth:** any time a job URL is seen from a new company, enqueue a registry-resolution task.

---

## 4. Crawl strategy

- **Cadence:** Greenhouse/Lever/Ashby/SmartRecruiters/Workable — every 6–12 h per board (cheap). Workday/iCIMS — every 12–24 h, low concurrency.
- **Politeness:** shared HTTP client, per-host token bucket, `User-Agent` identifying the project + contact, respect `robots.txt` for HTML fallbacks, honor `Retry-After`, exponential backoff + jitter, cap concurrency per provider (Workday=1/tenant).
- **Incremental:** per board, keep `{source_id: content_hash, seen_at}`. New id → new job. Changed hash → job-updated event (re-run eligibility). Missing id for K crawls → mark closed.
- **Normalization pipeline:** provider adapter → canonical `Job{company_id, ats, source_id, req_key, title, locations[], remote, employment_type, jd_text, jd_html, comp?, posted_at, updated_at, apply_url, source_urls[], content_hash}` → location parser (US? state, metro) → seniority parser → dedupe.
- **Stable identifiers by provider:** Greenhouse `internal_job_id`+`id`; Lever `id`(UUID); Ashby `jobId`+`id`; Workday `jobRequisitionId`; SmartRecruiters `id`+`refNumber`; Workable `shortcode`; USAJOBS `MatchedObjectId`.

---

## 5. Known cross-source problems

1. **Multi-location fan-out:** one req = N postings. Collapse on `req_key`, keep location array.
2. **Relative dates** (Workday) — cannot trust for freshness; use detail ISO date or hash-diff.
3. **HTML descriptions** vary wildly; strip to text early, keep raw HTML for the apply step.
4. **"Remote - US" vs "Remote" vs "US"** — needs an explicit allowlist parser; default unknown location → keep, tag `location_unknown`, let eligibility decide (per PRIMARY PRINCIPLE, don't drop).
5. **Reposts:** company closes and reopens a req with a new id — near-dedupe on title+company+jd simhash within 60 days.
6. **Same company, multiple ATSes** (migrating vendors) — registry allows >1 provider row per company; dedupe across them.
7. **Geo/IP gating:** some boards serve different results by region; run from a stable U.S. egress.
```
