"""
Aggregate read cache.

The cache exists to stop identical expensive reads from recomputing: the admin
aggregates are the same payload for every admin, and all ten behavioural
endpoints are projections of one pandas pass. These tests pin the properties
that make that safe — key isolation, TTL, and soft failure — using an in-memory
fake so no Redis server is needed.

The rest of the suite runs with the cache disabled (see conftest), so it is
enabled explicitly here.
"""

import json
from fnmatch import fnmatch
from typing import Dict, Optional
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import aggregate_cache


class _FakeRedis:
    """The subset of the Redis API the aggregate cache uses."""

    def __init__(self):
        self.values: Dict[str, str] = {}
        self.ttls: Dict[str, int] = {}
        self.fail = False
        self.writes = 0

    def get(self, key: str) -> Optional[str]:
        if self.fail:
            raise ConnectionError("redis down")
        return self.values.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None):
        if self.fail:
            raise ConnectionError("redis down")
        self.values[key] = value
        self.writes += 1
        if ex is not None:
            self.ttls[key] = ex
        return True

    def scan_iter(self, match: str, count: int = 100):
        if self.fail:
            raise ConnectionError("redis down")
        for key in list(self.values):
            if fnmatch(key, match):
                yield key

    def delete(self, key: str):
        self.values.pop(key, None)
        self.ttls.pop(key, None)


@pytest.fixture
def fake_redis():
    """Enable the cache and back it with the in-memory fake."""
    client = _FakeRedis()
    previous = settings.AGGREGATE_CACHE_ENABLED
    settings.AGGREGATE_CACHE_ENABLED = True
    with patch("app.services.aggregate_cache.get_redis", return_value=client):
        yield client
    settings.AGGREGATE_CACHE_ENABLED = previous


class TestKeys:
    def test_the_same_inputs_produce_the_same_key(self):
        first = aggregate_cache.cache_key("ns", "platform", {"days": 30, "a": 1})
        # Declaration order must not matter, or every caller would need to
        # build the dict identically.
        second = aggregate_cache.cache_key("ns", "platform", {"a": 1, "days": 30})
        assert first == second

    def test_different_params_produce_different_keys(self):
        assert aggregate_cache.cache_key("ns", "platform", {"days": 30}) != (
            aggregate_cache.cache_key("ns", "platform", {"days": 365})
        )

    def test_scope_separates_users(self):
        assert aggregate_cache.cache_key("ns", 1, {"days": 30}) != (
            aggregate_cache.cache_key("ns", 2, {"days": 30})
        )

    def test_namespace_separates_endpoints(self):
        assert aggregate_cache.cache_key("a", "platform", {}) != (
            aggregate_cache.cache_key("b", "platform", {})
        )


class TestReadWrite:
    def test_a_write_is_readable(self, fake_redis):
        aggregate_cache.write("ns", "platform", {"days": 7}, {"value": 1})
        assert aggregate_cache.read("ns", "platform", {"days": 7}) == {"value": 1}

    def test_a_miss_returns_none(self, fake_redis):
        assert aggregate_cache.read("ns", "platform", {"days": 7}) is None

    def test_a_different_scope_is_a_miss(self, fake_redis):
        aggregate_cache.write("ns", 1, {"days": 7}, {"value": 1})
        assert aggregate_cache.read("ns", 2, {"days": 7}) is None

    def test_entries_carry_the_configured_ttl(self, fake_redis):
        aggregate_cache.write("ns", "platform", {}, {"value": 1})
        assert set(fake_redis.ttls.values()) == {settings.AGGREGATE_CACHE_TTL_SECONDS}

    def test_get_or_compute_computes_once(self, fake_redis):
        calls = []

        def compute():
            calls.append(1)
            return {"value": len(calls)}

        first = aggregate_cache.get_or_compute("ns", "platform", {}, compute)
        second = aggregate_cache.get_or_compute("ns", "platform", {}, compute)
        assert first == second == {"value": 1}
        assert len(calls) == 1

    def test_invalidate_drops_the_namespace(self, fake_redis):
        aggregate_cache.write("ns", "platform", {"days": 7}, {"value": 1})
        aggregate_cache.invalidate("ns")
        assert aggregate_cache.read("ns", "platform", {"days": 7}) is None


class TestSafety:
    """A cache must never change what an endpoint returns, or whether it works."""

    def test_a_redis_outage_still_returns_a_computed_payload(self, fake_redis):
        fake_redis.fail = True
        result = aggregate_cache.get_or_compute("ns", "platform", {}, lambda: {"v": 2})
        assert result == {"v": 2}

    def test_a_corrupt_entry_reads_as_a_miss(self, fake_redis):
        key = aggregate_cache.cache_key("ns", "platform", {})
        fake_redis.values[key] = "{not json"
        assert aggregate_cache.read("ns", "platform", {}) is None

    def test_an_unserializable_payload_is_returned_but_not_cached(self, fake_redis):
        payload = {"when": object()}
        result = aggregate_cache.get_or_compute("ns", "platform", {}, lambda: payload)
        assert result is payload
        assert fake_redis.writes == 0

    def test_nothing_is_stored_when_the_cache_is_disabled(self, fake_redis):
        settings.AGGREGATE_CACHE_ENABLED = False
        try:
            aggregate_cache.write("ns", "platform", {}, {"value": 1})
            assert fake_redis.writes == 0
            assert aggregate_cache.read("ns", "platform", {}) is None
        finally:
            settings.AGGREGATE_CACHE_ENABLED = True

    def test_a_zero_ttl_disables_the_cache(self, fake_redis):
        previous = settings.AGGREGATE_CACHE_TTL_SECONDS
        settings.AGGREGATE_CACHE_TTL_SECONDS = 0
        try:
            assert aggregate_cache.enabled() is False
            aggregate_cache.write("ns", "platform", {}, {"value": 1})
            assert fake_redis.writes == 0
        finally:
            settings.AGGREGATE_CACHE_TTL_SECONDS = previous


class TestCachedEndpoints:
    """The payloads the endpoints actually cache must survive a round trip."""

    def test_the_admin_dashboard_payload_is_cacheable(
        self, client, admin_headers, fake_redis
    ):
        first = client.get("/api/v1/admin/dashboard", headers=admin_headers)
        assert first.status_code == 200
        assert fake_redis.writes == 1, "the payload was not JSON-serializable"

        second = client.get("/api/v1/admin/dashboard", headers=admin_headers)
        assert second.status_code == 200
        # Served from cache: the body is identical and nothing was recomputed.
        assert second.json() == first.json()
        assert fake_redis.writes == 1

    def test_the_behavioural_overview_is_shared_by_its_projections(
        self, client, auth_headers, fake_redis
    ):
        overview = client.get("/api/v1/analytics/behavioral", headers=auth_headers)
        assert overview.status_code == 200
        assert fake_redis.writes == 1

        # Each of these is a projection of the same overview, so none of them
        # may trigger a second pandas pass.
        for path in (
            "/api/v1/analytics/behavioral/snooze",
            "/api/v1/analytics/behavioral/wake-consistency",
            "/api/v1/analytics/behavioral/trends/monthly",
            "/api/v1/analytics/behavioral/habits",
        ):
            assert client.get(path, headers=auth_headers).status_code == 200
        assert fake_redis.writes == 1

    def test_a_different_window_is_computed_separately(
        self, client, auth_headers, fake_redis
    ):
        client.get("/api/v1/analytics/behavioral?days=30", headers=auth_headers)
        client.get("/api/v1/analytics/behavioral?days=7", headers=auth_headers)
        assert fake_redis.writes == 2

    def test_one_users_overview_is_never_served_to_another(
        self, client, auth_headers, admin_headers, fake_redis
    ):
        client.get("/api/v1/analytics/behavioral", headers=auth_headers)
        client.get("/api/v1/analytics/behavioral", headers=admin_headers)
        assert fake_redis.writes == 2
        assert len({json.loads(v).get("user_id") for v in fake_redis.values.values()}) <= 2
