# Dashboard performance harness

Four tools, one dataset shape:

| Tool | Layer measured | When to use |
|---|---|---|
| `perf/benchmark.py` | App + ORM + SQL, in-process | Find slow queries, N+1s, and missing indexes. Deterministic, no server needed. |
| `perf/capacity.py` | App + ORM + SQL under a concurrency ramp, in-process **or** over real HTTP (`--base-url`) | Answer *how many* concurrent users fit inside a latency SLA. |
| `perf/loadtest/locustfile.py` | Full HTTP stack under concurrency | Validate behaviour at N concurrent users over a real socket. |
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

## 2. Capacity ramp (in-process or against a live server)

`benchmark.py` answers "how fast is one request"; the load tests answer "does
20 users work". Neither answers **how many concurrent users this can serve**.
`capacity.py` ramps concurrency until the SLA breaks and reports the last level
that held:

```powershell
cd backend
python -m perf.capacity --profile medium --label capacity-sqlite
```

Each level replays a full `UserDashboard.jsx` page load (6 endpoints) per
simulated user, on its own account and its own connection, and records
throughput, p50/p95/p99 and failures. The highest level with zero failures and
`p95 <= --sla-p95-ms` is the measured capacity.

| Flag | Purpose |
|---|---|
| `--levels 1 5 10 25 50 100` | Concurrency ladder (ascending). |
| `--rounds N` | Page loads per simulated user per level. |
| `--sla-p95-ms` | Latency target a level must meet to count (default 1500). |
| `--no-stop-on-fail` | Keep ramping past the first failing level. |
| `--database-url` | Point at PostgreSQL — required for a meaningful number. |
| `--base-url` | Drive a **live HTTP server** instead of the in-process app. |
| `--request-timeout-s` | Per-request timeout in live mode; a timeout counts as a failure. |
| `--skip-seed` | Reuse a dataset an earlier step already loaded. |
| `--require-capacity N` | Exit non-zero if measured capacity drops below N users. |

The connection pool is sized above the peak level automatically, so the pool is
never the thing under test. **Run this against PostgreSQL.** SQLite takes a
database-level lock, so its ceiling describes the test rig, not the app; the
harness prints a warning saying so.

### 2.1 Live-server mode

Without `--base-url` the ramp calls the ASGI app in-process: no sockets, no
middleware stack timing, no serialization deserialization cost. That measures
the application, not the deployment. `--base-url` switches every simulated user
to a real HTTP client that logs in over the wire and reuses its token, so
middleware, JSON encoding, the socket layer and the worker model are all inside
the measurement.

```powershell
cd backend
docker compose up -d postgres
$PG = "postgresql+psycopg2://icap_perf:<password>@localhost:5432/icap_perf"

# 1. seed PostgreSQL and measure single-request cost with real query plans
python -m perf.benchmark --database-url $PG --profile medium --explain --label pg-baseline

# 2. start the API against the same database
$env:DATABASE_URL = $PG
Start-Process python -ArgumentList "-m","uvicorn","app.main:app","--port","8000","--workers","4"

# 3. ramp the live server, reusing the dataset from step 1
python -m perf.capacity --database-url $PG --base-url http://127.0.0.1:8000 `
    --skip-seed --profile medium --levels 1 5 10 25 50 100 `
    --require-capacity 25 --label pg-live-capacity
```

The harness waits for the server to become reachable before the first level, so
startup time is never billed as latency. `--database-url` is still required in
live mode: the ramp needs it to provision the per-user login accounts, and it
must be the same database the server is running against.

`backend/tests/test_concurrency_capacity.py` is the automated counterpart: it
runs with the normal pytest suite and asserts that 20 simultaneous users are
all served correctly, that no response is delivered to the wrong user, and that
latency degrades by queueing rather than collapsing.

## 3. Load test with Locust

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

## 4. Load test with k6

```powershell
k6 run -e BASE_URL=http://localhost:8000 `
       -e USER_EMAIL=perf-user-00000@perf.example.com -e USER_PASSWORD=<password> `
       -e ADMIN_EMAIL=perf-admin@perf.example.com -e ADMIN_PASSWORD=<password> `
       -e COACH_EMAIL=perf-coach@perf.example.com -e COACH_PASSWORD=<password> `
       perf/loadtest/k6_dashboard.js
```

Thresholds mirror the p95 budgets in `perf/benchmark.py`, so k6 exits non-zero
when a dashboard regresses.

## 5. Regression guards in CI

`tests/test_dashboard_performance.py` runs with the normal pytest suite. It
asserts query counts do not scale with the requested window and that the
dashboard read-path indexes stay declared. It contains no timing assertions,
so it is safe on shared CI runners.

`tests/test_api_latency.py`, `tests/test_challenge_generation_latency.py` and
`tests/test_concurrency_capacity.py` do assert wall-clock behaviour, against
budgets with enough headroom that only a structural regression trips them.

`tests/test_asset_delivery.py` guards the delivery path: cache-control and
immutability rules for hashed assets, the precompressed `.br`/`.gz` siblings,
and the CSP/CORS headers the CDN configuration depends on.

[`.github/workflows/performance.yml`](../../.github/workflows/performance.yml)
wires all of it together on every push and pull request:

| Job | Guards |
|---|---|
| `frontend-bundle-budget` | `npm run check:bundle-size` against `frontend/performance-budget.json`, plus `node scripts/precompress.js --verify`. |
| `backend-perf-guards` | The five pytest suites above. |
| `postgres-load-test` | Seeds a real `postgres:16-alpine` service, benchmarks it with `EXPLAIN ANALYZE`, starts uvicorn against it, then runs the capacity ramp in live mode with `--require-capacity 5`. |

The PostgreSQL job uses the `small` profile on push/PR and `medium` on the
weekly schedule, and uploads `perf/results/` as an artifact either way.

Two opt-in flags exist for manual and scheduled runs but are deliberately not
wired into per-push CI, because they fail on scenarios with known open items
(see section 8 of `docs/PERFORMANCE.md`):

- `perf/benchmark.py --fail-on-budget` — exit non-zero when any scenario's p95
  exceeds its budget.
- `perf/loadtest/k6_dashboard.js` thresholds — same budgets, enforced by k6.

## Notes on the numbers

- `SQL exec ms` brackets `cursor.execute` only. On SQLite the scan work happens
  lazily during fetch and is attributed to `App ms`; on PostgreSQL it lands in
  `SQL exec ms`. Compare like-for-like dialects.
- Generated artifacts (`perf/.perfdata/`, `perf/results/`) are git-ignored.
- Credentials are always read from the environment — no passwords are stored
  in these files.
