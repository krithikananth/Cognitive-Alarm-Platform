"""
Overlapping write routes must keep their distinct contracts.

Five routes look like duplicates of a canonical counterpart the frontend uses,
but each was measured against its twin and none is redundant:

* ``PATCH /profiles/me/goals`` takes a typed ``List[str]``; ``PUT
  /users/profile/goals`` is lenient and splits a comma string.
* ``PUT /auth/me`` is the only route that can change an email address;
  ``PUT /users/profile`` cannot write one at all.
* ``PUT /profiles/me`` writes the raw profile record, including fields the
  ``/users/profile`` bundle never exposes.
* ``GET /users`` and ``GET /admin/users`` must at least agree on the population.

These tests pin those differences so neither side is "cleaned up" on the
assumption that it is a duplicate.
"""

from app.models.profile import UserProfile
from app.models.user import User


def _profile(db_session, user_id: int) -> UserProfile:
    db_session.expire_all()
    return (
        db_session.query(UserProfile)
        .filter(UserProfile.user_id == user_id)
        .first()
    )


class TestProfileWriteAliases:
    """`/profiles/me` writes must land exactly where `/users/profile` does."""

    def test_sleep_schedule_alias_stores_the_same_state(
        self, client, auth_headers, test_user, db_session
    ):
        canonical = client.put(
            "/api/v1/users/profile/sleep-schedule",
            json={"preferred_wake_time": "06:15", "sleep_duration_hours": 7.5},
            headers=auth_headers,
        )
        assert canonical.status_code == 200
        after_canonical = _profile(db_session, test_user.id)
        canonical_state = (
            after_canonical.preferred_wake_time,
            after_canonical.sleep_duration_hours,
        )

        # Move it away so the alias has to do real work rather than no-op.
        client.put(
            "/api/v1/users/profile/sleep-schedule",
            json={"preferred_wake_time": "09:00", "sleep_duration_hours": 5.0},
            headers=auth_headers,
        )

        alias = client.patch(
            "/api/v1/profiles/me/sleep-schedule",
            json={"preferred_wake_time": "06:15", "sleep_duration_hours": 7.5},
            headers=auth_headers,
        )
        assert alias.status_code == 200
        after_alias = _profile(db_session, test_user.id)

        assert (
            after_alias.preferred_wake_time,
            after_alias.sleep_duration_hours,
        ) == canonical_state

    def test_the_two_goals_routes_accept_different_payloads(
        self, client, auth_headers, test_user, db_session
    ):
        """Same destination, deliberately different input contracts."""
        # The lenient route takes a comma string and splits it.
        lenient = client.put(
            "/api/v1/users/profile/goals",
            json={"productivity_goals": "deep work, reading"},
            headers=auth_headers,
        )
        assert lenient.status_code == 200
        assert _profile(db_session, test_user.id).productivity_goals == [
            "deep work",
            "reading",
        ]

        # The typed route rejects that same string outright.
        rejected = client.patch(
            "/api/v1/profiles/me/goals",
            json={"productivity_goals": "deep work, reading"},
            headers=auth_headers,
        )
        assert rejected.status_code == 422

        # Given a real list it writes the identical stored state.
        client.put(
            "/api/v1/users/profile/goals",
            json={"productivity_goals": "something else"},
            headers=auth_headers,
        )
        typed = client.patch(
            "/api/v1/profiles/me/goals",
            json={"productivity_goals": ["deep work", "reading"]},
            headers=auth_headers,
        )
        assert typed.status_code == 200
        assert _profile(db_session, test_user.id).productivity_goals == [
            "deep work",
            "reading",
        ]

    def test_profile_put_alias_updates_the_same_record(
        self, client, auth_headers, test_user, db_session
    ):
        response = client.put(
            "/api/v1/profiles/me",
            json={"timezone": "Europe/Berlin", "sleep_duration_hours": 6.5},
            headers=auth_headers,
        )
        assert response.status_code == 200

        stored = _profile(db_session, test_user.id)
        assert stored.timezone == "Europe/Berlin"
        assert stored.sleep_duration_hours == 6.5

        # And the canonical read reflects the alias write immediately.
        bundle = client.get("/api/v1/users/profile", headers=auth_headers)
        assert bundle.status_code == 200
        assert bundle.json()["timezone"] == "Europe/Berlin"


class TestCurrentUserWriteAlias:
    """`PUT /auth/me` owns the email address; `PUT /users/profile` does not."""

    def test_both_routes_update_the_shared_full_name(
        self, client, auth_headers, test_user, db_session
    ):
        response = client.put(
            "/api/v1/auth/me",
            json={"full_name": "Alias Written"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        db_session.expire_all()
        stored = db_session.query(User).filter(User.id == test_user.id).first()
        assert stored.full_name == "Alias Written"

        canonical = client.put(
            "/api/v1/users/profile",
            json={"full_name": "Canonical Written"},
            headers=auth_headers,
        )
        assert canonical.status_code == 200

        db_session.expire_all()
        stored = db_session.query(User).filter(User.id == test_user.id).first()
        assert stored.full_name == "Canonical Written"

    def test_only_auth_me_can_change_the_email_address(
        self, client, auth_headers, test_user, db_session
    ):
        original = test_user.email

        # The canonical profile route has no email field, so it silently
        # leaves the address alone — it is not an email-write path.
        canonical = client.put(
            "/api/v1/users/profile",
            json={"email": "rewritten@example.com"},
            headers=auth_headers,
        )
        assert canonical.status_code == 200
        db_session.expire_all()
        assert (
            db_session.query(User).filter(User.id == test_user.id).first().email
            == original
        )

        # /auth/me really does write it.
        alias = client.put(
            "/api/v1/auth/me",
            json={"email": "rewritten@example.com"},
            headers=auth_headers,
        )
        assert alias.status_code == 200
        db_session.expire_all()
        assert (
            db_session.query(User).filter(User.id == test_user.id).first().email
            == "rewritten@example.com"
        )

    def test_auth_me_rejects_an_email_already_in_use(
        self, client, auth_headers, admin_user
    ):
        response = client.put(
            "/api/v1/auth/me",
            json={"email": admin_user.email},
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestUserCollectionAlias:
    """`GET /users` and `GET /admin/users` must describe the same population."""

    def test_both_listings_return_the_same_users(self, client, admin_headers):
        plain = client.get("/api/v1/users/", headers=admin_headers)
        admin = client.get(
            "/api/v1/admin/users", params={"per_page": 100}, headers=admin_headers
        )
        assert plain.status_code == 200
        assert admin.status_code == 200

        plain_ids = {row["id"] for row in plain.json()}
        admin_ids = {row["id"] for row in admin.json()["users"]}
        assert plain_ids == admin_ids

    def test_the_plain_listing_is_admin_only(self, client, auth_headers):
        response = client.get("/api/v1/users/", headers=auth_headers)
        assert response.status_code == 403
