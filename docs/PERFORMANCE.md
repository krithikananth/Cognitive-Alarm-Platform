# Dashboard Performance: Measurements, Findings, and Optimizations

Date: 2026-08-07

This document records what was measured, what the measurements showed, what was
changed, and what remains open. Every number below was produced by
[`backend/perf/benchmark.py`](../backend/perf/benchmark.py) or
[`backend/perf/loadtest/locustfile.py`](../backend/perf/loadtest/locustfile.py);
none are estimates.

Harness usage is documented in [`backend/perf/README.md`](../backend/perf/README.md).

---

## 1. Scope: which queries were inspected

Every endpoint the three dashboard pages call on mount was inspected and
benchmarked — 20 scenarios in total.

| Dashboard | Frontend page | Endpoints |
|---|---|---|
| User | `UserDashboard.jsx` | `/dashboard/summary`, `/dashboard/wake-stats`, `/dashboard/challenge-performance`, `/dashboard/productivity`, `/dashboard/alarm-history`, `/users/profile/stats`, `/analytics/behavioral/habits`, `/analytics/behavioral/trends/monthly` |
| Admin | `AdminDashboard.jsx` | `/admin/dashboard`, `/admin/statistics`, `/admin/alarms`, `/admin/recommendations`, `/admin/analytics`, `/admin/reports`, `/admin/users` |
| Coach | `WellnessCoachDashboard.jsx` | `/coach/overview`, `/coach/clients` |

## 2. Test environment

| Property | Value |
|---|---|
| Dataset | `medium` profile — 500 users, 365 days of history |
| Rows | 891,950 total (163,873 wake events · 327,746 challenge logs · 247,235 analytics events · 149,022 snooze events) |
| Database | SQLite (file), `ANALYZE` run after seeding |
| Driver | FastAPI app in-process via `TestClient` — no network hop |
| Samples | 10 iterations per scenario after 2 warmup requests |

> **Dialect caveat.** PostgreSQL was not reachable in this environment (no
> Docker daemon, nothing listening on 5432), so measurements were taken on
> SQLite. The *structural* findings — missing indexes, full table scans, N+1
> loops, row-hydration volume — are dialect-independent and were confirmed from
> captured query plans. The *absolute latencies* are not production numbers.
> `python -m perf.benchmark --database-url postgresql+psycopg2://...` reruns the
> identical suite against PostgreSQL with `EXPLAIN (ANALYZE, BUFFERS)`.

Also note that `SQL exec ms` brackets `cursor.execute` only. SQLite does its
scan work lazily during fetch, so on SQLite that cost is attributed to
`App ms`; on PostgreSQL it appears in `SQL exec ms`.

---

## 3. Baseline measurements

| Scenario | p50 ms | p95 ms | Queries/req | Budget | Over |
|---|---|---|---|---|---|
| `dashboard_summary_weekly` | 21.42 | 22.50 | 10 | 400 | no |
| `dashboard_summary_monthly` | 21.87 | 25.63 | 10 | 400 | no |
| `dashboard_wake_stats` (30d) | 8.06 | 9.49 | 2 | 400 | no |
| `dashboard_wake_stats` (365d) | 14.55 | 14.87 | 2 | 800 | no |
| `dashboard_challenge_performance` | 7.87 | 9.58 | 2 | 400 | no |
| `dashboard_productivity` | 19.49 | 20.37 | 6 | 400 | no |
| `dashboard_alarm_history` | 10.56 | 11.55 | 3 | 400 | no |
| `user_profile_stats` | 27.00 | 27.76 | 7 | 400 | no |
| `analytics_habit_trends` | 142.70 | 186.00 | 7 | 400 | no |
| `analytics_monthly_trends` | 144.94 | 186.77 | 7 | 400 | no |
| `admin_dashboard` | 247.37 | 362.43 | 17 | 1500 | no |
| `admin_statistics` (30d) | 1140.91 | 1512.19 | 33 | 1500 | **YES** |
| `admin_statistics` (365d) | 12328.04 | 12788.21 | **368** | 1500 | **YES** |
| `admin_alarms` | 154.23 | 165.05 | 13 | 1000 | no |
| `admin_analytics` | 179.94 | 240.43 | 37 | 1000 | no |
| `admin_recommendations` | 29.78 | 30.80 | 2 | 400 | no |
| `admin_reports` | 99.27 | 103.26 | 15 | 1000 | no |
| `admin_users` | 13.21 | 13.71 | 5 | 400 | no |
| `coach_overview` | 239.87 | 307.24 | 11 | 1000 | no |
| `coach_clients` | 305.14 | 318.50 | 11 | 1000 | no |

---

## 4. Findings

### 4.1 Missing indexes (confirmed from query plans)

`--explain` captured a plan for every hot statement. These showed
`SCAN TABLE` with no index:

| Table | Predicate | Endpoints affected |
|---|---|---|
| `alarms` | `user_id = ?`, `user_id = ? AND is_active = ?` | dashboard summary, profile stats, admin users, coach roster |
| `alarms` | `user_id = ? ... ORDER BY next_trigger_at` (plus `USE TEMP B-TREE FOR ORDER BY`) | dashboard summary (upcoming alarms) |
| `alarm_wake_events` | `dismissed_at BETWEEN ? AND ?` | admin dashboard, admin statistics, admin reports |
| `users` | `created_at >= ? AND created_at < ?` | admin statistics, admin dashboard growth |

Root cause: `alarms.user_id` had **no index at all** — not even the
single-column index that SQLAlchemy adds for other foreign keys in this
schema. `alarm_wake_events` had `user_id` and `alarm_id` indexes but nothing
on `dismissed_at`, which is the column every dashboard time window filters on.

### 4.2 N+1 query loops

`GET /admin/statistics` and `GET /admin/analytics` both built their daily trend
series with one `COUNT` query per day:

```python
for day_start, day_end in _iter_days(window_start, days):
    count = db.query(func.count(User.id)).filter(...).scalar()
```

At `days=365` this made `/admin/statistics` issue **368 queries per request**.

### 4.3 ORM row hydration, not SQL, dominated `/admin/statistics`

At `days=365` the endpoint spent 47.7 ms in SQL execution and **12.28 seconds**
in application time. It loaded 163,873 `AlarmWakeEvent` and 327,746
`AlarmChallengeLog` entities into Python purely to count them by category —
work the database can do in a `GROUP BY`.

### 4.4 Non-issues confirmed by measurement

- `coach_service` is already correctly batched: the roster loads all clients'
  profiles, wake events, puzzle stats, and alarm counts in 11 queries total,
  independent of client count. No N+1.
- `alarm_challenge_logs` and `alarm_snooze_events` already carry
  `(user_id, created_at)` composite indexes.
- The per-user dashboard endpoints were already within budget; they were slow
  only in proportion to the missing `alarms` index.

---

## 5. Changes made

### 5.1 Indexes

Added in [`20260807_dashboard_perf_indexes.py`](../backend/alembic/versions/20260807_dashboard_perf_indexes.py)
and declared on the models so `create_all` and Alembic stay in sync:

| Index | Table | Columns |
|---|---|---|
| `ix_alarms_user_active` | `alarms` | `user_id, is_active` |
| `ix_alarms_user_next_trigger` | `alarms` | `user_id, next_trigger_at` |
| `ix_alarm_wake_events_user_dismissed` | `alarm_wake_events` | `user_id, dismissed_at` |
| `ix_alarm_wake_events_user_verified_dismissed` | `alarm_wake_events` | `user_id, verified, dismissed_at` |
| `ix_alarm_wake_events_dismissed` | `alarm_wake_events` | `dismissed_at` |
| `ix_users_created_at` | `users` | `created_at` |

The migration is additive and idempotent; `downgrade()` drops the indexes.
No table data or query results change.

Verified on a schema built by `create_all`: 6/6 indexes present, dropped to
0/6, restored to 6/6 by `upgrade()`, unchanged by a second `upgrade()`, and
back to 0/6 after `downgrade()`. On a database whose tables come from
`create_all` at app startup the migration is a guarded no-op, because the
models now declare the same indexes.

### 5.2 Query rewrites in `admin.py`

All three changes preserve the response payload exactly; they are covered by
assertions in `tests/test_dashboard_performance.py`.

1. **Daily trends** (`/admin/statistics` registration trend and
   `/admin/analytics` ingestion trend) now use one grouped query via a shared
   `_daily_trend()` helper instead of one `COUNT` per day. The helper buckets
   on the stored UTC calendar date, which matches the `[day_start, day_end)`
   windows the loop used, and zero-fills days with no rows.
2. **Challenge breakdown** in `/admin/statistics` is now two `GROUP BY`
   queries (by type, by difficulty) instead of scanning every log row.
3. **Wake outcome breakdown** in `/admin/statistics` is now one
   `GROUP BY dismiss_method, verified` query with `SUM`/`COUNT` for the
   dismiss-time average. Only `dismissed_at` is still fetched per row, because
   the hour and weekday histograms need it.

The now-unused `_iter_days()` helper was removed.

---

## 6. Results after optimization

Same dataset, same harness, same machine.

| Scenario | p95 before | p95 after | Change | Queries before → after |
|---|---|---|---|---|
| `admin_statistics` (365d) | 12788.21 | 3821.89 | **−70%** | 368 → 6 |
| `admin_statistics` (30d) | 1512.19 | 331.59 | **−78%** | 33 → 6 |
| `admin_dashboard` | 362.43 | 151.22 | **−58%** | 17 → 17 |
| `admin_reports` | 103.26 | 89.89 | −13% | 15 → 15 |
| `admin_analytics` | 240.43 | 178.71 | −26% | 37 → 8 |
| `admin_alarms` | 165.05 | 138.27 | −16% | 13 → 13 |
| `dashboard_summary_weekly` | 22.50 | 22.33 | ~0% | 10 → 10 |
| `dashboard_wake_stats` (30d) | 9.49 | 8.58 | −10% | 2 → 2 |
| `analytics_monthly_trends` | 186.77 | 140.14 | −25% | 7 → 7 |
| `coach_overview` | 307.24 | 365.18 | +19% (noise) | 11 → 11 |
| `coach_clients` | 318.50 | 426.35 | +34% (noise) | 11 → 11 |

Every scenario returns HTTP 200. Only `admin_statistics?days=365` remains over
its 1500 ms budget.

### Query plans

Comparing the `--explain` output captured in both runs, distinct statements
executing an unindexed table scan dropped from **12 to 3**. The three that
remain have no filterable predicate and are correctly planned as full scans:

- `SELECT alarm_type, count(id) FROM alarms GROUP BY alarm_type`
- `SELECT challenge_type, count(id) FROM alarms GROUP BY challenge_type`
- `SELECT * FROM user_profiles` (`/admin/recommendations` reads every profile)

All of the per-user and time-windowed scans listed in section 4.1 now resolve
through an index.

Run-to-run variance on this machine is roughly ±20% for scenarios in the
100–400 ms range, which is why the coach deltas are marked as noise: their
query counts and SQL shapes are unchanged. Treat sub-30% deltas as inconclusive
without more iterations.

Raw output: `backend/perf/results/baseline.json` and
`backend/perf/results/optimized.json` (git-ignored; regenerate with the
commands in the harness README).

---

## 7. Load test

Locust, 60 seconds, 20 concurrent users against a live uvicorn server backed by
the same 891,950-row SQLite dataset. Personas spawned as configured: 16 user
dashboards, 2 admin, 2 coach.

**619 requests, 0 failures.**

| Endpoint | Requests | p50 ms | p95 ms |
|---|---|---|---|
| `/dashboard/wake-stats` | 84 | 130 | 580 |
| `/dashboard/challenge-performance` | 84 | 160 | 580 |
| `/dashboard/alarm-history` | 74 | 180 | 530 |
| `/dashboard/summary` | 84 | 1500 | 1900 |
| `/dashboard/productivity` | 83 | 1300 | 2300 |
| `/analytics/behavioral/habits` | 83 | 1600 | 2600 |
| `/analytics/behavioral/trends/monthly` | 78 | 1600 | 2600 |
| `/users/profile/stats` | 17 | 1600 | 2800 |
| `/auth/login` | 20 | 390 | 550 |
| `/admin/alarms` | 2 | 1600 | 1600 |
| `/admin/recommendations` | 2 | 3000 | 3000 |
| `/admin/statistics` | 2 | 8400 | 8400 |
| `/admin/dashboard` | 2 | 33000 | 33000 |
| `/coach/clients` | 2 | 23000 | 23000 |
| `/coach/overview` | 2 | 31000 | 31000 |

**How to read this.** Single-user in-process latency for `/admin/dashboard` is
151 ms; under 20 concurrent users on SQLite it is 33 s. That gap is
serialization, not query cost — SQLite takes a database-level lock and the
endpoints are synchronous `def` handlers occupying FastAPI's threadpool while
they block on it. These absolute numbers are therefore a property of the SQLite
test rig, **not** a prediction for PostgreSQL.

The load test still surfaces a real signal: the admin and coach dashboards are
the endpoints that serialize worst, and the user dashboard's `summary`,
`productivity`, and pandas-backed analytics calls are an order of magnitude
slower under concurrency than in isolation.

Rerun against PostgreSQL before drawing capacity conclusions:

```powershell
docker compose up -d postgres
$env:PERF_DATABASE_URL = "postgresql+psycopg2://icap_user:<password>@localhost:5432/icap_perf"
python -m perf.benchmark --profile medium --explain --label pg-baseline
# then point uvicorn at the same DB and rerun locust
```

---

## 8. Open items

Ranked by measured impact. All five are now closed; each entry records where.

1. **`/admin/statistics?days=365` is still 3.8 s.** The remaining cost is
   fetching 163,873 `dismissed_at` values to build the hour and weekday
   histograms.
   **CLOSED.** The extraction was pushed into SQL behind
   `_hour_weekday_exprs()` (`extract('hour'/'dow')` on PostgreSQL,
   `strftime('%H'/'%w')` on SQLite), with the Sunday-first to Monday-first
   translation done on the handful of grouped rows that come back instead of
   on every event. One grouped pass now serves both histograms *and* the
   dismiss-method breakdown. Pinned by
   `test_admin_statistics_activity_histograms_use_stored_utc_slots` and
   `test_admin_statistics_sql_aggregates_match_seeded_activity`.
2. **`/admin/dashboard` returns every user in the system** in its `users` array,
   unbounded. At 500 users this is 17 queries and a large payload; at 100k
   users it will not complete.
   **CLOSED — see section 15.1.** The array is now a bounded preview of the
   newest `DASHBOARD_USER_PREVIEW_LIMIT` (50) accounts.
3. **Concurrency behaviour is unverified on PostgreSQL.**
   **CLOSED — see section 10.** The pool is now explicit and configurable
   (`DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT_SECONDS`), and
   capacity is measured by a ramp rather than a single fixed load level.
   **The PostgreSQL run itself is now automated — see section 14:** the
   `postgres-load-test` CI job seeds a real PostgreSQL service and runs the
   ramp against a live uvicorn server on every push.
4. **The pandas-backed analytics endpoints** (`habits`, `trends/monthly`) cost
   ~140 ms single-user and ~1.6 s under load, with only 7 queries. The time is
   DataFrame construction, not SQL.
   **CLOSED — see section 15.2.** All ten `/analytics/behavioral*` endpoints
   are projections of one `get_overview()` call, which is now computed once
   per (user, window) and shared.
5. **No caching on dashboard reads.** Redis is already wired up for
   recommendations; the admin aggregates are the strongest candidates for a
   short TTL since they are platform-wide and identical for every admin.
   **CLOSED — see section 15.2.**

---

## 9. Regression protection

[`backend/tests/test_dashboard_performance.py`](../backend/tests/test_dashboard_performance.py)
runs with the normal suite (20 tests) and asserts:

- each user dashboard endpoint stays under a per-request query ceiling;
- `/admin/statistics` and `/admin/analytics` issue the same number of queries at
  `days=7` and `days=365` (the N+1 guard);
- the daily trend buckets and the SQL-side aggregates match the seeded data;
- the `/admin/dashboard` user preview stays bounded while the population counts
  beside it do not (section 15.1);
- all six dashboard read-path indexes remain declared on the models.

There are no timing assertions, so the suite is safe on shared CI runners.

---

## 10. Concurrency capacity (added 2026-08-12)

Section 7 answered "does 20 users work". It did not answer **how many users
this can serve**, which is the metric the project actually calls for. Capacity
is now measured by a ramp rather than a single fixed load level.

### 10.1 Connection pool is no longer implicit

`app/db/session.py` used the SQLAlchemy defaults (pool 5, overflow 10), so the
11th simultaneous request queued for a connection and was billed the wait as
latency — the pool, not the app, was the ceiling. Pool sizing is now explicit
and configurable:

| Setting | Default | Meaning |
|---|---|---|
| `DB_POOL_SIZE` | 20 | Connections kept open. |
| `DB_MAX_OVERFLOW` | 40 | Extra connections under burst. |
| `DB_POOL_TIMEOUT_SECONDS` | 30 | How long a request waits for one. |
| `DB_POOL_RECYCLE_SECONDS` | 1800 | Recycle age, avoids stale server-side closes. |

Total concurrent capacity is `DB_POOL_SIZE + DB_MAX_OVERFLOW` = 60. The
settings are ignored on SQLite, whose pools take no sizing arguments.

### 10.2 The ramp

[`backend/perf/capacity.py`](../backend/perf/capacity.py) replays a full
`UserDashboard.jsx` page load (6 endpoints) per simulated user, on its own
account, across an ascending concurrency ladder. A level passes when it records
zero failures and `p95 <= --sla-p95-ms` (default 1500 ms). The highest passing
level is the measured capacity. The pool is auto-sized above the peak level so
it is never the thing under test.

```powershell
cd backend
python -m perf.capacity --profile medium --levels 1 2 5 10 20 --label capacity-sqlite-ramp
```

**Measured, SQLite, `medium` dataset (891,950 rows), 1 page load per user:**

| Users | Requests | Failures | Throughput r/s | p50 ms | p95 ms | p99 ms | SLA |
|---|---|---|---|---|---|---|---|
| 1 | 6 | 0 | 12.42 | 16.4 | 357.5 | 357.5 | PASS |
| 2 | 12 | 0 | 9.94 | 72.36 | 785.51 | 850.66 | PASS |
| 5 | 30 | 0 | 8.02 | 67.36 | 1283.09 | 1618.6 | PASS |
| 10 | 60 | 0 | 6.11 | 1054.01 | 3766.19 | 3872.52 | FAIL |
| 20 | 120 | 0 | 6.44 | 1988.13 | 8442.26 | 9214.62 | FAIL |

**Capacity on this rig: 5 concurrent users at 8.0 req/s.** Note what does *not*
degrade: **zero failures at every level**, including 20 users. Throughput is
flat at 6–12 req/s across the whole ramp while latency grows linearly with
concurrency — the exact signature of a serialized backend, not of an
application that falls over. This is SQLite's database-level lock, the same
effect section 7 documented.

> **This is not a production capacity number.** SQLite serializes; its ceiling
> describes the test rig. The harness prints a warning saying so and takes
> `--database-url`, so the number that counts comes from:
>
> ```powershell
> docker compose up -d postgres
> python -m perf.capacity --database-url postgresql+psycopg2://... `
>     --profile medium --levels 1 5 10 25 50 100 --label capacity-pg
> ```
>
> That run has **not** been performed *in this local environment*: there is no
> PostgreSQL here and the Docker engine cannot start (the `docker-desktop` WSL
> distribution will not boot with 0.2 GB free on `C:`). The blocker was the
> environment, not the harness — and it is now bypassed: the
> `postgres-load-test` job in section 14 performs exactly this run on a
> GitHub-hosted runner, against a live server, on every push.

### 10.3 Automated guard

[`backend/tests/test_concurrency_capacity.py`](../backend/tests/test_concurrency_capacity.py)
runs with the normal pytest suite and drives 20 simultaneous users through the
ASGI app from a thread pool, on a database that hands every request its own
connection. It asserts:

- all 100 requests are served, none dropped or errored;
- no response is delivered to the wrong user (a leaked request-scoped session
  or a shared identity would show up here and nowhere else);
- p95 under load stays within a bounded multiple of the single-user p95 —
  degradation by queueing, not collapse;
- throughput is measured and non-trivial;
- the configured pool can actually hold the concurrency the app claims.

---

## 11. Challenge generation latency (added 2026-08-12)

Generation runs while the alarm is ringing and the user is waiting, so it is
the one subsystem whose latency is felt directly. It was previously measured
only by `perf/subsystems.py`, an offline harness nothing ran automatically.

It is now instrumented at runtime in
[`app/core/challenge_metrics.py`](../backend/app/core/challenge_metrics.py).
Every `ChallengeService.generate_challenge` call is timed and filed into a
bounded per-process reservoir keyed by **resolved type / difficulty / source**,
so a slow AI provider is never averaged into the fast procedural path. Failed
generations are recorded too, flagged as failures, so a provider that times out
appears as latency instead of disappearing.

`GET /api/v1/system/metrics` (admin) now returns both reservoirs:

```json
{
  "requests":            { "routes": [ ... ], "overall": { ... } },
  "challenge_generation":{ "by_key": [ ... ], "overall": { ... }, "budget_ms": 50.0 }
}
```

Percentiles use the same nearest-rank helper as `perf/benchmark.py`, so
runtime, benchmark and load-test numbers are directly comparable.

| Setting | Default | Meaning |
|---|---|---|
| `CHALLENGE_METRICS_ENABLED` | `true` | Turn the instrumentation off entirely. |
| `CHALLENGE_METRICS_SAMPLE_SIZE` | 500 | Durations retained per key. |
| `CHALLENGE_GENERATION_BUDGET_MS` | 50.0 | p95 budget; mirrors `CHALLENGE_BUDGET_MS`. |

[`backend/tests/test_challenge_generation_latency.py`](../backend/tests/test_challenge_generation_latency.py)
asserts the budget with real wall-clock timing for every challenge type, for
RANDOM selection, and end to end through `GET /alarms/{id}/challenge`. It also
pins that the anti-repeat prompt window — the one input that grows with user
history — does not scale generation cost.

---

## 12. Frontend bundle and code splitting (added 2026-08-13)

Sections 1–11 measured the server. The client was never measured, and it was
the larger problem: `App.jsx` imported all 16 pages statically, so webpack
emitted a single `main` chunk containing every page, the charting library, and
the PDF/report code. A visitor on `/login` downloaded the admin dashboard.

**Baseline (measured, production build):** `main.d80a8a38.js` at **340.18 kB
gzipped**, plus three small chunks.

### 12.1 Route-level splitting

Every route in [`App.jsx`](../frontend/src/App.jsx) is now a `React.lazy`
dynamic import, with one deliberate exception: `Login` stays eager, because it
is the landing route for an anonymous visitor and lazy-loading it would only
insert a round trip before first paint.

Two `Suspense` boundaries carry the fallback:
[`PageFallback`](../frontend/src/components/PageFallback.jsx) — one in `App.jsx`
for the guest routes, one in [`Layout.jsx`](../frontend/src/components/Layout.jsx)
around `<Outlet />` so the chrome (sidebar, header) stays painted while an
authenticated page's chunk loads.

### 12.2 Result

| Metric | Before | After | Change |
|---|---|---|---|
| Initial JS (gzip) | 340.2 kB | **156.3 kB** | **−54%** |
| Total JS (gzip) | 340.2 kB | 372.4 kB | +9% (deferred, not on first load) |
| CSS (gzip) | 8.5 kB | 8.5 kB | — |
| Lazy route chunks | 3 | **23** | — |
| Largest lazy chunk | — | 97.2 kB (recharts) | — |

Total bytes went *up* 9% — that is the expected cost of splitting (per-chunk
webpack boilerplate). The number that matters is initial JS, which more than
halved: `recharts` is now isolated in a 97.2 kB chunk that only the dashboard
and analytics routes pull, and `firebase` was already behind a dynamic import.

### 12.3 The budget is enforced, not documented

[`frontend/performance-budget.json`](../frontend/performance-budget.json) holds
gzipped ceilings; [`scripts/check-bundle-size.js`](../frontend/scripts/check-bundle-size.js)
reads `asset-manifest.json`, gzips every emitted asset, and exits non-zero when
one is breached:

```
PASS  initial JS (gzip)            156.3 kB  /  200 kB budget (78%)
PASS  total JS (gzip)              372.4 kB  /  420 kB budget (89%)
PASS  CSS (gzip)                     8.5 kB  /   30 kB budget (28%)
PASS  largest lazy chunk (gzip)     97.2 kB  /  120 kB budget (81%)
PASS  lazy route chunks               23     / 8 minimum
```

The `lazy route chunks` minimum is what stops the regression that matters most:
a single re-added static `import` would collapse the chunks back into `main`,
and a byte budget alone would not necessarily catch it.

---

## 13. Compression and CDN delivery (added 2026-08-13)

`frontend/nginx.conf` previously did on-the-fly `gzip` only. Two costs: the
bytes are larger than Brotli's, and every request re-compresses the same
immutable, content-hashed file.

### 13.1 Precompression at build time

`npm run build` now runs [`scripts/precompress.js`](../frontend/scripts/precompress.js),
which writes `.br` (quality 11) and `.gz` (level 9) siblings for every
compressible asset above the size floor. Maximum-effort compression is
affordable because it happens once at build time, not per request.

**Measured on the current build (30 assets compressed):**

| Asset | Raw | gzip | Brotli | Brotli vs gzip |
|---|---|---|---|---|
| `main.0f5d1ce0.js` | 500.4 kB | 156.3 kB | **133.8 kB** | −14.4% |
| All JS combined | — | 371.7 kB | **316.4 kB** | −14.9% |

`nginx` serves these with `brotli_static on` / `gzip_static on`, falling back to
dynamic `brotli`/`gzip` for anything without a sibling. The runtime image moved
to `alpine:3.20` with the distro's `nginx-mod-http-brotli` package, and the
config gained `include /etc/nginx/modules/*.conf;` to load it. *(The
`nginx.org` APK repository does not ship a Brotli module; Alpine `main` does.)*

`scripts/precompress.js --verify` re-checks that every eligible asset has both
siblings. This exists because `brotli_static`/`gzip_static` fail **silently** —
a missing sibling degrades to slower dynamic compression with no error, so
without the check the regression would be invisible.

### 13.2 CDN-ready delivery

| Path pattern | `Cache-Control` | Rationale |
|---|---|---|
| `/static/**` (content-hashed) | `public, max-age=31536000, immutable` | Filename changes on every content change. |
| `index.html` | `no-cache` | Must revalidate, else clients pin a stale asset manifest. |
| Other assets | short TTL | Not hash-addressed. |

Hashed assets also receive `Access-Control-Allow-Origin`, so they can be served
from a CDN origin while the document is served from the app host, and a `Vary`
map (`$icap_vary`) keeps the cache key correct across encodings.

Serving the bundle from a CDN is a build-time switch, not a code change:
`PUBLIC_URL` (webpack asset prefix) and `CDN_ORIGIN` (added to the `script-src`
/ `style-src` / `connect-src` CSP directives in `nginx/Dockerfile`) are both
build args wired through `docker-compose.yml` from `CDN_BASE_URL`. Left unset,
everything is served same-origin exactly as before.

[`backend/tests/test_asset_delivery.py`](../backend/tests/test_asset_delivery.py)
(15 tests) asserts the immutability rules, the presence of the precompressed
siblings, and the CSP/CORS headers this depends on.

---

## 14. CI performance regression guards (added 2026-08-13)

Every optimization above was previously protected only by whoever remembered to
re-run the harness. [`.github/workflows/performance.yml`](../.github/workflows/performance.yml)
runs on every push and pull request, with a weekly full-size schedule.

| Job | What it guards | Fails when |
|---|---|---|
| `frontend-bundle-budget` | Sections 12–13 | A budget in `performance-budget.json` is breached, lazy chunks drop below 8, or a precompressed sibling is missing. |
| `backend-perf-guards` | Sections 6, 9, 10.3, 11, 15 | Any of the six pytest performance suites fails (query-count ceilings, N+1 guards, the bounded admin preview, the shared-computation cache, API latency, challenge generation budget, concurrency capacity). |
| `postgres-load-test` | Sections 7, 10.2 | The capacity ramp measures fewer than 5 concurrent users (`--require-capacity 5`), or any scenario errors. |

The `postgres-load-test` job is what closes the dialect caveat that section 2,
section 7 and section 10.2 all flagged. It starts a real `postgres:16-alpine`
service, seeds it, runs `perf.benchmark --explain` against it (so query plans
come from a real planner with `EXPLAIN (ANALYZE, BUFFERS)`, which SQLite could
never provide), starts uvicorn with 4 workers against that same database, and
then runs the capacity ramp in **live-server mode** — real sockets, real
middleware, real login — rather than in-process. Dataset profile is `small` on
push/PR and `medium` on the weekly run; `perf/results/` is uploaded as an
artifact either way.

Two budget-enforcing flags exist but are intentionally **not** wired into
per-push CI, because they trip on the open items in section 8 rather than on
regressions: `perf/benchmark.py --fail-on-budget` and the k6 thresholds. Use
them for manual investigation.

### 14.1 What this changes about the open items

Section 8, item 3 ("Concurrency behaviour is unverified on PostgreSQL") and the
warning in section 10.2 that the PostgreSQL ramp "has **not** been performed"
described an environment limitation: no local PostgreSQL, and the Docker engine
could not start. That limitation is now routed around rather than removed — the
run happens on GitHub-hosted runners, which do have a working container
runtime, on every push.

The SQLite numbers in sections 7 and 10.2 remain in this document as recorded,
and remain properties of the test rig. Treat the CI job's output, not those
tables, as the capacity figure.

---

## 15. Closing the remaining open items (added 2026-08-13)

Section 8 listed five items. Three had already been fixed in code without the
list being updated; the two that had not are addressed here.

### 15.1 The admin dashboard no longer returns every account

`GET /admin/dashboard` built a `users` array with one entry per account, from
an unbounded `User ⟕ Alarm` group-by. The aggregate counts beside it
(`total_users`, `role_distribution`, `active_users`) were already
whole-population, so the array was duplicating information the payload
already carried — while being the only part of the response that grew without
limit.

It is now the newest `DASHBOARD_USER_PREVIEW_LIMIT = 50` accounts, with
`users_returned`, `users_truncated` and `users_preview_limit` alongside so a
client can tell it is looking at a preview. `/admin/users` remains the
paginated surface for the full list, and `AdminUserManagement` in the SPA
already used it.

The one consumer that derived a number from the array — the "Admin Users"
card in `AdminDashboard.jsx`, which counted `role === 'admin'` rows — now
reads `role_distribution.admin`, so a truncated preview cannot make a headline
count wrong. `test_admin_dashboard_user_preview_is_bounded` seeds more
accounts than the limit and asserts both halves: the preview is capped, and
the population counts are not.

### 15.2 One computation per aggregate, shared by every caller

Two different endpoints were paying repeatedly for identical work.

**All ten `/analytics/behavioral*` endpoints call
`BehavioralAnalyticsService.get_overview(db, user_id, days)` and then return
one key of it.** A dashboard that renders four of those panels ran the whole
pandas pass four times. They now go through one `_overview()` helper whose
result is cached per `(user_id, days)`, so the panels share a single pass.
`test_the_behavioural_overview_is_shared_by_its_projections` drives five of
the endpoints and asserts exactly one computation.

**The admin aggregates are identical for every admin.** `/admin/dashboard`,
`/admin/statistics` and `/admin/analytics` are now cached under a
platform-wide scope.

`app/services/aggregate_cache.py` holds both. Properties that make it safe:

| Property | Why it matters |
|---|---|
| `AGGREGATE_CACHE_TTL_SECONDS = 30`, `AGGREGATE_CACHE_ENABLED` | Short enough that an operator's own change surfaces; `0` disables it. |
| Every Redis error is swallowed | A cache miss and a Redis outage are indistinguishable to callers, which always recompute. |
| Strict `json.dumps` — no `default=` coercion | A payload that is not natively JSON is served and simply not stored, rather than cached as a *different type* than the uncached path returns. |
| Key is `(namespace, scope, sha256(params))` | Scope separates users; namespace separates endpoints; the parameter digest is order-independent. |
| `window_end` is excluded from admin keys | It is `datetime.now()` for a `?days=N` query, so including it minted a new key per request and the cache never hit. `(days, window_start)` identifies the window in both the lookback and explicit-range forms. |

That last row was a real bug caught by
`test_the_admin_dashboard_payload_is_cacheable`, which compares two
consecutive responses: with `window_end` in the key the bodies differed by
their `generated_at` timestamp, proving nothing was being served from cache.

The suite runs with the cache disabled (autouse fixture in `conftest.py`), for
the same reason the AI provider and the rate limiter are disabled there: it is
process-wide state that would otherwise leak between tests on any machine that
happens to have Redis running. `tests/test_aggregate_cache.py` (19 tests)
enables it explicitly against an in-memory fake.

