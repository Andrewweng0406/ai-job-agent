# WORKER_CONCURRENCY.md — Application Worker Model, Claims & Leases

**Author:** Claude (reviewer)
**Updated:** 2026-09-07
**Purpose:** define how multiple application workers share the queue without two workers ever actively
owning the same application, and without a crashed/slow worker causing a duplicate submission.

---

## 1. Roles

| Worker | Count (target) | Job |
|---|---|---|
| Discovery | 2–3 | crawl boards, normalize, dedupe, upsert jobs, create `DISCOVERED`/`ELIGIBLE` applications |
| Queue | 1 | `ELIGIBLE → QUEUED` (persona resolve), enforce daily caps, order by priority |
| Resume | 2 | `QUEUED → TAILORING → READY` (retrieve facts, generate, validate, PDF) |
| Application | 1 now → **3–4 after gates** | `READY/RETRY_PENDING → APPLYING → SUBMITTED → …` (form fill, dry-run, controlled submit) |
| Verify | 2 | async: `SUBMITTED/SUBMISSION_UNKNOWN → VERIFIED` via evidence tiers; open human tasks at window close |
| Reaper | 1 (cron) | expire stale leases, requeue orphaned work |

Only **Application** and **Discovery** workers contend; the rest are naturally serialized or read-mostly.

---

## 2. Claim + lease model

Add to `applications`:
```sql
ALTER TABLE applications ADD COLUMN worker_id     TEXT;
ALTER TABLE applications ADD COLUMN lease_expires_at TEXT;   -- ISO-8601 UTC
ALTER TABLE applications ADD COLUMN lease_epoch   INTEGER NOT NULL DEFAULT 0;
CREATE INDEX idx_applications_claimable
    ON applications(status, lease_expires_at);
```

### 2.1 Atomic claim (compare-and-set, single statement)
```sql
UPDATE applications
   SET status = 'APPLYING',
       worker_id = :me,
       lease_expires_at = :now_plus_ttl,
       lease_epoch = lease_epoch + 1
 WHERE application_id = :id
   AND status IN ('READY','RETRY_PENDING')
   AND (worker_id IS NULL OR lease_expires_at < :now);
-- proceed IFF changes()/rowcount == 1
```
The claim also writes an `application_state_transitions` row (`→ APPLYING`) in the same
`BEGIN IMMEDIATE` transaction. `lease_epoch` is the fencing token.

### 2.2 Pick work
```sql
SELECT application_id FROM applications
 WHERE status IN ('READY','RETRY_PENDING')
   AND (worker_id IS NULL OR lease_expires_at < :now)
 ORDER BY queued_at ASC
 LIMIT :batch;
```
Then try to claim each; skip the ones where `rowcount != 1` (another worker won).

### 2.3 Heartbeat / renew
Long form-fills renew the lease every `TTL/3`:
```sql
UPDATE applications SET lease_expires_at = :now_plus_ttl
 WHERE application_id = :id AND worker_id = :me AND lease_epoch = :my_epoch;
```
If renew affects 0 rows, the worker has **lost the lease** → it must abort immediately (do not submit).

### 2.4 Release
On completion/failure, the terminal transition clears the lease:
```sql
UPDATE applications SET worker_id = NULL, lease_expires_at = NULL
 WHERE application_id = :id AND worker_id = :me AND lease_epoch = :my_epoch;
```

### 2.5 Fencing (the critical safety property)
Every side-effecting step (especially `adapter.submit()`) checks the fence first:
```
assert repository.lease_still_mine(application_id, worker_id=me, epoch=my_epoch)
```
A returning zombie worker A (lease expired, B reclaimed and bumped `lease_epoch`) fails this check and
**cannot** submit. TTL must exceed the per-application hard timeout (e.g. TTL = 10 min, app cap = 6 min)
so a live-but-slow worker isn't preempted mid-submit.

---

## 3. Reaper

Runs every 60 s:
- Rows in `APPLYING`/`TAILORING` with `lease_expires_at < now - grace`:
  - if a submit had already fired (transcript shows `submit_time` set / evidence partial) →
    `SUBMISSION_UNKNOWN` (verify worker takes it; **never** auto-retry).
  - else → `RETRY_PENDING` (clear lease; `attempt_count` unchanged — the claim will bump it).
- Rows in `SUBMITTED` older than the verification window with no evidence → `SUBMISSION_UNKNOWN`.
- Emits `lease.reaped` events with the prior `worker_id`.

Crash recovery = the reaper. No special restart logic: a process that dies mid-`APPLYING` leaves a row
whose lease simply expires and is reclaimed safely.

---

## 4. Per-domain / per-ATS throttling

Independent of the DB lease — a shared limiter keyed by company domain and by ATS:

| Scope | Limit | Enforcement |
|---|---|---|
| per company (submissions) | 1 concurrent, ≥ N sec between submits | in-process semaphore + last-submit timestamp table `domain_pacing(host, last_at, cooldown_until)` |
| per ATS (all HTTP) | GH/Lever ~5 req/s, Ashby ~4 req/s | shared token bucket in the HTTP client |
| per company after CAPTCHA/block | `cooldown_until = now + 30–60 min` | claim query also excludes jobs whose company is in cooldown |

A worker that can't get a domain slot **releases the lease and picks other work** — it does not spin
holding the application.

---

## 5. Duplicate-submission defense in depth

1. `applications.dedupe_key UNIQUE` (requisition-based) — only one application row per real requisition.
2. Atomic claim — only one worker in `APPLYING` at a time.
3. Fencing token — a stale worker can't act after losing the lease.
4. Idempotency row written **before** the form opens — a crash after submit leaves a recoverable
   `APPLYING`/`SUBMISSION_UNKNOWN`, never nothing.
5. `SUBMISSION_UNKNOWN` has **no path back to `APPLYING`** (state machine).
6. Workflow refuses to run unless status ∈ {`READY`,`RETRY_PENDING`} (checked against **DB**, not the
   in-memory object).
7. Verify worker, not the apply worker, promotes to `VERIFIED`.

If any one of these is missing, `application_concurrency` must stay at 1.

---

## 6. Shutdown / restart

- SIGTERM: workers stop claiming, finish or abort the current step (abort if a submit hasn't fired;
  if it has, hand to verify), release leases, exit.
- On restart: nothing to do — reaper handles any leases that outlived the process.
- Leases are DB state, not memory, so a full-fleet restart is safe.

---

## 7. Config

```yaml
workers:
  application_concurrency: 1        # -> 3 or 4 ONLY after Round 2.5 gates pass
  lease_ttl_seconds: 600
  application_hard_timeout_seconds: 360
  heartbeat_interval_seconds: 200
  reaper_interval_seconds: 60
rate_limits:
  per_company_submit_min_gap_seconds: 45
  per_company_cooldown_after_block_seconds: 2700
  ats_requests_per_second: { greenhouse: 5, lever: 5, ashby: 4 }
```

---

## 8. Tests (`tests/test_worker_lease.py`, spec until the layer lands)

- claim: 2/4/8 concurrent claimers on one application ⇒ exactly one `rowcount==1`
- lease expiry: worker A claims, "dies" (no renew), TTL passes, worker B reclaims (`lease_epoch` bumped)
- fencing: worker A returns after expiry ⇒ `lease_still_mine` False ⇒ `submit()` not called
- reaper: `APPLYING` past grace with submit fired ⇒ `SUBMISSION_UNKNOWN`; without ⇒ `RETRY_PENDING`
- per-company: 2 workers, same company ⇒ second blocks / picks other work, never concurrent submit
- shutdown mid-`APPLYING` (pre-submit) ⇒ lease released ⇒ reclaimable, `attempt_count` bumped once on reclaim
- no scenario produces two `→ SUBMITTED` transitions for one `application_id`
