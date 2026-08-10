"""Locust load test for the ICAP dashboard APIs.

Runs against a live backend over HTTP, so it measures the full stack
(uvicorn + FastAPI + connection pool + database) under concurrency — the part
``perf/benchmark.py`` deliberately excludes.

Setup::

    pip install -r perf/requirements-perf.txt

Headless run (user dashboard only)::

    locust -f perf/loadtest/locustfile.py \
        --host http://localhost:8000 \
        --users 50 --spawn-rate 5 --run-time 3m --headless \
        --tags user

Web UI with all three dashboard personas::

    locust -f perf/loadtest/locustfile.py --host http://localhost:8000

Credentials are read from the environment. Each simulated user picks an
account from ``PERF_USER_EMAILS`` (comma-separated) so requests spread across
distinct data sets instead of hammering one warm row::

    PERF_USER_EMAILS=a@x.test,b@x.test
    PERF_USER_PASSWORD=...
    PERF_ADMIN_EMAIL=admin@x.test
    PERF_ADMIN_PASSWORD=...
    PERF_COACH_EMAIL=coach@x.test
    PERF_COACH_PASSWORD=...

Never point this at production: it issues a sustained read load and logs in
repeatedly.
"""

from __future__ import annotations

import itertools
import os
import random

from locust import HttpUser, between, events, tag, task

API = "/api/v1"

_user_emails = [
    e.strip()
    for e in os.getenv("PERF_USER_EMAILS", "perf-user-00000@perf.example.com").split(",")
    if e.strip()
]
_email_cycle = itertools.cycle(_user_emails)

DAYS_CHOICES = [7, 30, 90]


@events.test_start.add_listener
def _warn_on_missing_credentials(environment, **_kwargs):
    if not os.getenv("PERF_USER_PASSWORD"):
        environment.runner.quit()
        raise RuntimeError(
            "PERF_USER_PASSWORD is not set — refusing to run without explicit "
            "load-test credentials."
        )


class _AuthenticatedUser(HttpUser):
    """Base class that logs in once and reuses the bearer token."""

    abstract = True
    wait_time = between(1, 3)

    email_env = "PERF_USER_EMAIL"
    password_env = "PERF_USER_PASSWORD"

    def on_start(self) -> None:
        email = os.getenv(self.email_env) or next(_email_cycle)
        password = os.getenv(self.password_env) or os.getenv("PERF_USER_PASSWORD")
        with self.client.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
            name=f"{API}/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login failed: {response.status_code}")
                self.environment.runner.quit()
                return
            token = response.json().get("access_token")
        self.client.headers.update({"Authorization": f"Bearer {token}"})


@tag("user")
class UserDashboardUser(_AuthenticatedUser):
    """Mirrors the request mix issued by frontend/src/pages/UserDashboard.jsx."""

    weight = 8
    email_env = "PERF_USER_EMAIL"

    @task(5)
    def dashboard_page_load(self) -> None:
        """The six parallel calls the dashboard fires on mount."""
        days = random.choice(DAYS_CHOICES)
        period = {7: "weekly", 30: "monthly", 90: "monthly"}[days]
        self.client.get(
            f"{API}/dashboard/summary",
            params={"period": period},
            name=f"{API}/dashboard/summary",
        )
        self.client.get(
            f"{API}/dashboard/wake-stats",
            params={"days": days},
            name=f"{API}/dashboard/wake-stats",
        )
        self.client.get(
            f"{API}/dashboard/challenge-performance",
            params={"days": days},
            name=f"{API}/dashboard/challenge-performance",
        )
        self.client.get(
            f"{API}/dashboard/productivity",
            params={"days": days},
            name=f"{API}/dashboard/productivity",
        )
        self.client.get(
            f"{API}/analytics/behavioral/habits",
            params={"days": days},
            name=f"{API}/analytics/behavioral/habits",
        )
        self.client.get(
            f"{API}/analytics/behavioral/trends/monthly",
            params={"days": days},
            name=f"{API}/analytics/behavioral/trends/monthly",
        )

    @task(3)
    def alarm_history_paging(self) -> None:
        self.client.get(
            f"{API}/dashboard/alarm-history",
            params={"page": random.randint(1, 3), "per_page": 20, "days": 30},
            name=f"{API}/dashboard/alarm-history",
        )

    @task(1)
    def profile_stats(self) -> None:
        self.client.get(f"{API}/users/profile/stats")


@tag("admin")
class AdminDashboardUser(_AuthenticatedUser):
    """Mirrors frontend/src/pages/AdminDashboard.jsx (6 parallel calls)."""

    weight = 1
    email_env = "PERF_ADMIN_EMAIL"
    password_env = "PERF_ADMIN_PASSWORD"

    @task(3)
    def admin_page_load(self) -> None:
        days = random.choice([7, 30])
        params = {"days": days}
        for path in (
            "/admin/dashboard",
            "/admin/statistics",
            "/admin/alarms",
            "/admin/recommendations",
            "/admin/analytics",
        ):
            self.client.get(f"{API}{path}", params=params, name=f"{API}{path}")
        self.client.get(f"{API}/admin/reports")

    @task(1)
    def admin_user_list(self) -> None:
        self.client.get(
            f"{API}/admin/users",
            params={"page": 1, "per_page": 20, "sort_by": "created_at"},
            name=f"{API}/admin/users",
        )


@tag("coach")
class CoachDashboardUser(_AuthenticatedUser):
    """Mirrors frontend/src/pages/WellnessCoachDashboard.jsx."""

    weight = 1
    email_env = "PERF_COACH_EMAIL"
    password_env = "PERF_COACH_PASSWORD"

    @task(2)
    def coach_page_load(self) -> None:
        days = random.choice([7, 30])
        self.client.get(
            f"{API}/coach/overview", params={"days": days}, name=f"{API}/coach/overview"
        )
        self.client.get(
            f"{API}/coach/clients",
            params={"page": 1, "per_page": 20},
            name=f"{API}/coach/clients",
        )
