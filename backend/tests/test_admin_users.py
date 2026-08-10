"""Tests for GET /api/v1/admin/users — the admin user-management list.

Covers the search, filter, sort and pagination contract the Admin User
Management UI depends on.
"""
from datetime import time

import pytest

from app.models.alarm import Alarm
from app.models.user import User, UserRole
from app.utils.hashing import get_password_hash


@pytest.fixture
def user_fixtures(db_session, admin_user):
    """Create a small, deterministic population alongside the admin user."""
    users = [
        User(
            email="zara@example.com",
            username="zara",
            hashed_password=get_password_hash("TestPass123"),
            full_name="Zara Coach",
            role=UserRole.WELLNESS_COACH,
            is_active=True,
            is_verified=True,
        ),
        User(
            email="brian@example.com",
            username="brian",
            hashed_password=get_password_hash("TestPass123"),
            full_name="Brian User",
            role=UserRole.USER,
            is_active=False,
            is_verified=False,
        ),
        User(
            email="cara@example.com",
            username="cara",
            hashed_password=get_password_hash("TestPass123"),
            full_name="Cara User",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        ),
    ]
    db_session.add_all(users)
    db_session.commit()
    for u in users:
        db_session.refresh(u)

    # Give "cara" two alarms so aggregate sorting has something to order by.
    db_session.add_all([
        Alarm(user_id=users[2].id, title="A1", alarm_time=time(6, 0)),
        Alarm(user_id=users[2].id, title="A2", alarm_time=time(7, 0)),
    ])
    db_session.commit()
    return users


class TestAdminListUsersAccess:
    """Authorization for the admin user list."""

    def test_requires_admin(self, client, test_user, auth_headers):
        response = client.get("/api/v1/admin/users", headers=auth_headers)
        assert response.status_code == 403

    def test_requires_authentication(self, client):
        response = client.get("/api/v1/admin/users")
        assert response.status_code == 401


class TestAdminListUsers:
    """Listing, pagination, search, filtering and sorting."""

    def test_returns_paginated_envelope(
        self, client, admin_headers, user_fixtures
    ):
        response = client.get("/api/v1/admin/users", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4  # admin + 3 fixtures
        assert data["page"] == 1
        assert data["total_pages"] == 1
        assert len(data["users"]) == 4

        row = data["users"][0]
        for field in (
            "id", "email", "username", "full_name", "role",
            "is_active", "is_verified", "created_at",
            "total_alarms", "verified_wakes",
        ):
            assert field in row

    def test_pagination_splits_results(
        self, client, admin_headers, user_fixtures
    ):
        first = client.get(
            "/api/v1/admin/users",
            params={"page": 1, "per_page": 2, "sort_by": "username", "sort_order": "asc"},
            headers=admin_headers,
        ).json()
        second = client.get(
            "/api/v1/admin/users",
            params={"page": 2, "per_page": 2, "sort_by": "username", "sort_order": "asc"},
            headers=admin_headers,
        ).json()

        assert first["total_pages"] == 2
        assert len(first["users"]) == 2
        assert len(second["users"]) == 2

        # No row appears on both pages.
        first_ids = {u["id"] for u in first["users"]}
        second_ids = {u["id"] for u in second["users"]}
        assert first_ids.isdisjoint(second_ids)

    def test_search_matches_email_or_username(
        self, client, admin_headers, user_fixtures
    ):
        response = client.get(
            "/api/v1/admin/users",
            params={"search": "zara"},
            headers=admin_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["users"][0]["username"] == "zara"

    def test_search_is_case_insensitive(
        self, client, admin_headers, user_fixtures
    ):
        response = client.get(
            "/api/v1/admin/users",
            params={"search": "BRIAN@EXAMPLE"},
            headers=admin_headers,
        )

        assert response.json()["total"] == 1

    def test_filter_by_role(self, client, admin_headers, user_fixtures):
        response = client.get(
            "/api/v1/admin/users",
            params={"role": "user"},
            headers=admin_headers,
        )

        data = response.json()
        assert data["total"] == 2
        assert {u["role"] for u in data["users"]} == {"user"}

    def test_filter_by_active_status(self, client, admin_headers, user_fixtures):
        inactive = client.get(
            "/api/v1/admin/users",
            params={"is_active": False},
            headers=admin_headers,
        ).json()

        assert inactive["total"] == 1
        assert inactive["users"][0]["username"] == "brian"

    def test_invalid_role_filter_rejected(
        self, client, admin_headers, user_fixtures
    ):
        response = client.get(
            "/api/v1/admin/users",
            params={"role": "superuser"},
            headers=admin_headers,
        )

        assert response.status_code == 400

    def test_sort_by_username(self, client, admin_headers, user_fixtures):
        asc = client.get(
            "/api/v1/admin/users",
            params={"sort_by": "username", "sort_order": "asc"},
            headers=admin_headers,
        ).json()
        desc = client.get(
            "/api/v1/admin/users",
            params={"sort_by": "username", "sort_order": "desc"},
            headers=admin_headers,
        ).json()

        asc_names = [u["username"] for u in asc["users"]]
        desc_names = [u["username"] for u in desc["users"]]
        assert asc_names == sorted(asc_names)
        assert desc_names == list(reversed(asc_names))

    def test_sort_by_full_name(self, client, admin_headers, user_fixtures):
        """full_name is a UI column and must be sortable server-side."""
        response = client.get(
            "/api/v1/admin/users",
            params={"sort_by": "full_name", "sort_order": "asc"},
            headers=admin_headers,
        )

        assert response.status_code == 200
        names = [u["full_name"] for u in response.json()["users"]]
        assert names == sorted(names)

    def test_sort_by_total_alarms(self, client, admin_headers, user_fixtures):
        """Aggregate sorting orders across the whole set, not just one page."""
        response = client.get(
            "/api/v1/admin/users",
            params={"sort_by": "total_alarms", "sort_order": "desc"},
            headers=admin_headers,
        )

        assert response.status_code == 200
        rows = response.json()["users"]
        assert rows[0]["username"] == "cara"
        assert rows[0]["total_alarms"] == 2
        counts = [u["total_alarms"] for u in rows]
        assert counts == sorted(counts, reverse=True)

    def test_sort_by_status(self, client, admin_headers, user_fixtures):
        response = client.get(
            "/api/v1/admin/users",
            params={"sort_by": "is_active", "sort_order": "asc"},
            headers=admin_headers,
        )

        assert response.status_code == 200
        assert response.json()["users"][0]["is_active"] is False

    def test_unknown_sort_field_rejected(
        self, client, admin_headers, user_fixtures
    ):
        response = client.get(
            "/api/v1/admin/users",
            params={"sort_by": "hashed_password"},
            headers=admin_headers,
        )

        assert response.status_code == 422

    def test_search_and_filter_combine(
        self, client, admin_headers, user_fixtures
    ):
        response = client.get(
            "/api/v1/admin/users",
            params={"search": "example.com", "role": "user", "is_active": True},
            headers=admin_headers,
        )

        data = response.json()
        assert data["total"] == 1
        assert data["users"][0]["username"] == "cara"
