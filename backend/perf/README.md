# Dashboard performance harness

Three tools, one dataset shape:

| Tool | Layer measured | When to use |
|---|---|---|
| `perf/benchmark.py` | App + ORM + SQL, in-process | Find slow queries, N+1s, and missing indexes. Deterministic, no server needed. |
| `perf/loadtest/locustfile.py` | Full HTTP stack under concurrency | Validate behaviour at N concurrent users. |
| `perf/loadtest/k6_dashboard.js` | Full HTTP stack under concurrency | Same as Locust, for k6-based CI. |

Measured results and the analysis behind them live in
[`docs/PERFORMANCE.md`](../../docs/PERFORMANCE.md).

## 1. Benchmark (no server required)

```powershell
cd backend
python -m perf.benchmark --profile medium --iterations 10 --explain --label baseline
```

Seeds a deterministic dataset, drives the real FastAPI app through
`TestClient`, and writes `perf/results/<label>.json` containing per-scenario
p50/p95/p99, queries per request, SQL execute time, and captured query plans.

Useful flags:

| Flag | Purpose |
|---|---|
| `--profile small\|medium\|large` | Dataset size (23k / 892k / ~3.5M rows). |
| `--skip-seed` | Reuse the existing dataset — required for a fair A/B run. |
| `--explain` | Capture `EXPLAIN QUERY PLAN` (SQLite) or `EXPLAIN (ANALYZE, BUFFERS)` (PostgreSQL). |
| `--only <keys>` | Restrict to specific scenarios. |
| `--database-url` | Benchmark against PostgreSQL instead of the default SQLite file. |

Before/after comparison:

```powershell
python -m perf.benchmark --profile medium --explain --label before
# apply the change
python -m perf.benchmark --skip-seed --explain --label after
```

### Benchmarking against PostgreSQL

SQLite is the default because it needs no services, but index behaviour and
planner decisions only fully match production on PostgreSQL:

```powershell
docker compose up -d postgres
$env:PERF_DATABASE_URL = "postgresql+psycopg2://icap_user:<password>@localhost:5432/icap_perf"
python -m perf.benchmark --profile medium --explain --label pg-baseline
```

`--database-url` points at a **throwaway** database: seeding drops and
recreates every table. Never aim it at production or a shared environment.

## 2. Load test with Locust

```powershell
pip install -r perf/requirements-perf.txt

$env:PERF_USER_EMAILS = "perf-user-00000@perf.example.com,perf-user-00001@perf.example.com"
$env:PERF_USER_PASSWORD = "<load-test account password>"
$env:PERF_ADMIN_EMAIL = "perf-admin@perf.example.com"
$env:PERF_ADMIN_PASSWORD = "<load-test admin password>"
$env:PERF_COACH_EMAIL = "perf-coach@perf.example.com"
$env:PERF_COACH_PASSWORD = "<load-test coach password>"

locust -f perf/loadtest/locustfile.py --host http://localhost:8000 `
       --users 50 --spawn-rate 5 --run-time 3m --headless --tags user
```

Tags `user`, `admin`, and `coach` select which dashboard persona runs. Each
persona issues the same request mix as the corresponding React page.

## 3. Load test with k6

```powershell
k6 run -e BASE_URL=http://localhost:8000 `
       -e USER_EMAIL=perf-user-00000@perf.example.com -e USER_PASSWORD=<password> `
       -e ADMIN_EMAIL=perf-admin@perf.example.com -e ADMIN_PASSWORD=<password> `
       -e COACH_EMAIL=perf-coach@perf.example.com -e COACH_PASSWORD=<password> `
       perf/loadtest/k6_dashboard.js
```

Thresholds mirror the p95 budgets in `perf/benchmark.py`, so k6 exits non-zero
when a dashboard regresses.

## 4. Regression guards in CI

`tests/test_dashboard_performance.py` runs with the normal pytest suite. It
asserts query counts do not scale with the requested window and that the
dashboard read-path indexes stay declared. It contains no timing assertions,
so it is safe on shared CI runners.

## Notes on the numbers

- `SQL exec ms` brackets `cursor.execute` only. On SQLite the scan work happens
  lazily during fetch and is attributed to `App ms`; on PostgreSQL it lands in
  `SQL exec ms`. Compare like-for-like dialects.
- Generated artifacts (`perf/.perfdata/`, `perf/results/`) are git-ignored.
- Credentials are always read from the environment — no passwords are stored
  in these files.
