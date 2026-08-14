"""
Concurrent user handling capacity, asserted automatically.

The Locust harness in ``perf/loadtest`` measures capacity properly against a
live server, but it needs a separate dependency set, a running uvicorn, seeded
credentials and a human to read the CSV. Nothing in the automated suite ever
proved the app serves simultaneous users *correctly* — that no request is
dropped, no response is corrupted by another user's session, and that latency
degrades proportionally rather than collapsing.

This module drives real concurrent traffic through the ASGI app from a thread
pool and asserts exactly that. It runs against a dedicated engine with a
connection *per request* (the shared `client` fixture deliberately injects one
session into every request, which is not safe to use concurrently).

What this does and does not claim: it proves correctness and bounded
degradation under concurrency on SQLite, which serializes writes at the
database level. It does not establish a production capacity ceiling — that is
what ``perf/capacity.py`` measures, against Postgres, with a real server.
"""

import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.request_metrics import PROCESS_TIME_HEADER, percentile
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User, UserRole
from app.utils.hashing import get_password_hash

#: Simultaneous users driven at the app. Matches the Locust run in
#: docs/PERFORMANCE.md section 7 so the two are comparable.
CONCURRENT_USERS = 20
#: Requests each simulated user issues.
REQUESTS_PER_USER = 5
#: Read-only endpoints a dashboard page load fans out to. Writes are excluded
#: on purpose: SQLite serializes them and that would measure the test rig.
READ_PATHS = [
    ("/api/v1/system/status", {}),
    ("/api/v1/alarms", {}),
    ("/api/v1/dashboard/wake-stats", {"days": 30}),
    ("/api/v1/dashboard/challenge-performance", {"days": 30}),
    ("/api/v1/auth/me", {}),
]
#: p95 under load may be this many times the single-user p95 before it counts
#: as a collapse rather than queueing. Generous: 20 users on one SQLite
#: connection are expected to queue.
DEGRADATION_ALLOWANCE = 60.0
#: Threads per core the allowance above was calibrated on (20 users, 8 cores).
#: The single-user baseline is measured serially, so it cannot see CPU
#: contention; a 2-core CI runner contends ~4x harder for the same work and
#: would read as a collapse. `_degradation_allowance` rescales for that, while
#: HARD_CEILING_MS still bounds the absolute latency on every machine.
REFERENCE_THREADS_PER_CPU = CONCURRENT_USERS / 8
#: Nothing here may take longer than this on any machine.
HARD_CEILING_MS = 15000.0


def _degradation_allowance() -> float:
    oversubscription = CONCURRENT_USERS / (os.cpu_count() or 1)
    return DEGRADATION_ALLOWANCE * max(
        1.0, oversubscription / REFERENCE_THREADS_PER_CPU
    )


@pytest.fixture(scope="module")
def concurrent_app():
    """App wired to an engine that hands each request its own connection.

    The suite-wide fixture shares one SQLite connection across every request
    (``StaticPool``), which cannot be driven from several threads at once —
    concurrent statements interleave on the same handle and corrupt parameter
    binding. A shared-cache in-memory database gives every pooled connection a
    view of the same data while keeping each thread on its own handle, and
    needs no disk. ``keeper`` holds the database alive: a shared-cache memory
    database is dropped when its last connection closes.
    """
    engine = create_engine(
        "sqlite:///file:icap_concurrency_capacity"
        "?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False, "uri": True, "timeout": 30},
        # SQLAlchemy pins memory databases to SingletonThreadPool; a real pool
        # is what makes "one connection per concurrent request" true here.
        poolclass=QueuePool,
        pool_size=CONCURRENT_USERS + 5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    keeper = engine.connect()
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield engine, Session
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        keeper.close()
        engine.dispose()


@pytest.fixture(scope="module")
def load_users(concurrent_app):
    """One account per simulated user, so no two threads share a session."""
    from app.models.profile import UserProfile

    _, Session = concurrent_app
    db = Session()
    try:
        users = []
        for i in range(CONCURRENT_USERS):
            user = User(
                email=f"load{i}@example.com",
                username=f"loaduser{i}",
                hashed_password=get_password_hash("LoadTest123"),
                full_name=f"Load User {i}",
                role=UserRole.USER,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            users.append(user)
        db.commit()
        # Rows the read paths would otherwise lazily create on first hit. They
        # are provisioned here so the measured phase performs no writes: on
        # SQLite a write would serialize every reader and measure the rig.
        for user in users:
            db.add(UserProfile(user_id=user.id))
        db.commit()
        return [{"id": u.id, "email": u.email} for u in users]
    finally:
        db.close()


@pytest.fixture(scope="module")
def load_client(concurrent_app, load_users):
    from app.services.system_settings_service import SystemSettingsService

    with TestClient(app) as c:
        _, Session = concurrent_app
        db = Session()
        try:
            SystemSettingsService.get_or_create(db)
        finally:
            db.close()
        # Serial warm-up: import caches, compiled statements and any remaining
        # lazy row creation happen on one thread before the measured phase.
        for path, params in READ_PATHS:
            c.get(path, params=params, headers=_headers(load_users[0]))
        yield c


def _headers(user):
    from app.core.security import create_access_token

    token = create_access_token(data={"sub": str(user["id"]), "role": "user"})
    return {"Authorization": f"Bearer {token}"}


def _server_ms(response):
    """Server-side duration from the timing middleware, excluding the client."""
    return float(response.headers.get(PROCESS_TIME_HEADER, 0.0))


def _user_session(client, user, requests_per_user):
    """One simulated user's whole visit. Returns (durations, failures)."""
    headers = _headers(user)
    durations, failures = [], []
    for i in range(requests_per_user):
        path, params = READ_PATHS[i % len(READ_PATHS)]
        try:
            response = client.get(path, params=params, headers=headers)
        except Exception as exc:  # noqa: BLE001 — a raised error is a failure
            failures.append(f"{path}: {type(exc).__name__}: {exc}")
            continue
        if response.status_code != 200:
            failures.append(f"{path}: HTTP {response.status_code}")
            continue
        # Prove the response belongs to the user that asked for it
        if path == "/api/v1/auth/me" and response.json()["id"] != user["id"]:
            failures.append(
                f"/auth/me returned user {response.json()['id']} to {user['id']}"
            )
        durations.append(_server_ms(response))
    return durations, failures


def _run_concurrently(client, users, *, requests_per_user=REQUESTS_PER_USER):
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(users)) as pool:
        results = list(
            pool.map(
                lambda u: _user_session(client, u, requests_per_user), users
            )
        )
    elapsed = time.perf_counter() - started

    durations = [d for batch, _ in results for d in batch]
    failures = [f for _, batch in results for f in batch]
    return {
        "durations": durations,
        "failures": failures,
        "requests": len(durations) + len(failures),
        "elapsed_s": elapsed,
        "throughput_rps": (len(durations) + len(failures)) / max(elapsed, 1e-9),
    }


class TestConcurrentUsers:
    def test_twenty_simultaneous_users_are_all_served(self, load_client, load_users):
        result = _run_concurrently(load_client, load_users)

        assert result["failures"] == [], (
            f"{len(result['failures'])} of {result['requests']} requests failed: "
            f"{result['failures'][:5]}"
        )
        assert result["requests"] == CONCURRENT_USERS * REQUESTS_PER_USER

    def test_responses_are_not_crossed_between_concurrent_users(
        self, load_client, load_users
    ):
        """Every /auth/me must answer the caller, never a neighbour.

        A shared session or a leaked request-scoped dependency shows up here
        first, and would be invisible to a single-threaded test.
        """
        def whoami(user):
            response = load_client.get("/api/v1/auth/me", headers=_headers(user))
            return user["id"], response.status_code, response.json().get("id")

        with ThreadPoolExecutor(max_workers=len(load_users)) as pool:
            observed = list(pool.map(whoami, load_users * 3))

        assert all(status == 200 for _, status, _ in observed)
        crossed = [(want, got) for want, _, got in observed if want != got]
        assert crossed == [], f"{len(crossed)} responses went to the wrong user"

    def test_concurrency_degrades_by_queueing_not_by_collapsing(
        self, load_client, load_users
    ):
        """Latency may rise under load, but proportionally to the queue."""
        serial = _run_concurrently(
            load_client, load_users[:1], requests_per_user=len(READ_PATHS) * 4
        )
        concurrent = _run_concurrently(load_client, load_users)

        baseline_p95 = max(percentile(serial["durations"], 95), 0.5)
        loaded_p95 = percentile(concurrent["durations"], 95)

        assert loaded_p95 <= HARD_CEILING_MS, (
            f"p95 under {CONCURRENT_USERS} users was {loaded_p95:.0f}ms"
        )
        allowance = _degradation_allowance()
        assert loaded_p95 <= baseline_p95 * allowance, (
            f"p95 went from {baseline_p95:.1f}ms single-user to "
            f"{loaded_p95:.1f}ms under {CONCURRENT_USERS} users "
            f"({loaded_p95 / baseline_p95:.1f}x, allowed {allowance:.1f}x on "
            f"{os.cpu_count()} cores)"
        )

    def test_throughput_is_reported_and_non_trivial(self, load_client, load_users):
        result = _run_concurrently(load_client, load_users)

        assert result["throughput_rps"] > 1.0, (
            f"only {result['throughput_rps']:.2f} req/s across "
            f"{result['requests']} requests"
        )
        assert statistics.mean(result["durations"]) > 0.0

    def test_the_pool_is_sized_for_the_configured_concurrency(self):
        """The connection pool is the hard ceiling on simultaneous users."""
        from app.core.config import settings

        capacity = settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW
        assert capacity >= CONCURRENT_USERS, (
            f"pool allows {capacity} concurrent connections, which cannot "
            f"serve {CONCURRENT_USERS} simultaneous users"
        )
        assert settings.DB_POOL_TIMEOUT_SECONDS > 0
