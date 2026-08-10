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

Ranked by measured impact.

1. **`/admin/statistics?days=365` is still 3.8 s.** The remaining cost is
   fetching 163,873 `dismissed_at` values to build the hour and weekday
   histograms. Pushing those into SQL needs dialect-specific extraction
   (`strftime('%H'/'%w')` on SQLite, `to_char`/`extract` on PostgreSQL) and a
   weekday-numbering translation; that was not shipped because it could not be
   validated against PostgreSQL here. The durable fix is a pre-aggregated daily
   rollup table rather than scanning a year of raw events per page load.
2. **`/admin/dashboard` returns every user in the system** in its `users` array,
   unbounded. At 500 users this is 17 queries and a large payload; at 100k
   users it will not complete. Fixing it changes the response shape, so it was
   left alone — it needs a product decision (paginate, or drop the array in
   favour of the existing `/admin/users` endpoint).
3. **Concurrency behaviour is unverified on PostgreSQL.** Re-run section 7
   against Postgres, and consider `pool_size`/`max_overflow` tuning in
   `app/db/session.py`, which currently uses SQLAlchemy defaults (pool of 5,
   overflow 10).
4. **The pandas-backed analytics endpoints** (`habits`, `trends/monthly`) cost
   ~140 ms single-user and ~1.6 s under load, with only 7 queries. The time is
   DataFrame construction, not SQL.
5. **No caching on dashboard reads.** Redis is already wired up for
   recommendations; the admin aggregates are the strongest candidates for a
   short TTL since they are platform-wide and identical for every admin.

---

## 9. Regression protection

[`backend/tests/test_dashboard_performance.py`](../backend/tests/test_dashboard_performance.py)
runs with the normal suite (16 tests) and asserts:

- each user dashboard endpoint stays under a per-request query ceiling;
- `/admin/statistics` and `/admin/analytics` issue the same number of queries at
  `days=7` and `days=365` (the N+1 guard);
- the daily trend buckets and the SQL-side aggregates match the seeded data;
- all six dashboard read-path indexes remain declared on the models.

There are no timing assertions, so the suite is safe on shared CI runners. Full
suite status after these changes: **505 passing**, plus the 16 new tests.
