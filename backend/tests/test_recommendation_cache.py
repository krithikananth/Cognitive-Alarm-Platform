"""
Tests for Redis-backed recommendation caching.

Uses an in-memory fake Redis so tests do not require a live server.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from unittest.mock import patch

import pytest

from app.core.redis_client import reset_redis_client
from app.models.profile import UserProfile
from app.schemas.recommendation import (
    DailyPlan,
    RecommendationCategory,
    RecommendationItem,
    RecommendationPriority,
    RecommendationResponse,
    RecommendationSummary,
)
from app.services.recommendation_cache import RecommendationCache
from app.services.recommendation_service import RecommendationService


class _FakePipeline:
    def __init__(self, store: "_FakeRedis"):
        self._store = store
        self._ops: List[tuple] = []

    def set(self, key: str, value: str, ex: Optional[int] = None):
        self._ops.append(("set", key, value, ex))
        return self

    def sadd(self, key: str, *members: str):
        self._ops.append(("sadd", key, members))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        for op in self._ops:
            kind = op[0]
            if kind == "set":
                _, key, value, ex = op
                self._store.set(key, value, ex=ex)
            elif kind == "sadd":
                _, key, members = op
                self._store.sadd(key, *members)
            elif kind == "expire":
                _, key, ttl = op
                self._store.expire(key, ttl)
        self._ops.clear()
        return []


class _FakeRedis:
    """Minimal Redis subset used by RecommendationCache."""

    def __init__(self):
        self.values: Dict[str, str] = {}
        self.sets: Dict[str, Set[str]] = {}
        self.ttls: Dict[str, int] = {}
        self.fail_next = False

    def ping(self):
        if self.fail_next:
            raise ConnectionError("redis down")
        return True

    def get(self, key: str) -> Optional[str]:
        if self.fail_next:
            raise ConnectionError("redis down")
        return self.values.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None):
        if self.fail_next:
            raise ConnectionError("redis down")
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def sadd(self, key: str, *members: str):
        bucket = self.sets.setdefault(key, set())
        bucket.update(members)
        return len(members)

    def smembers(self, key: str) -> Set[str]:
        return set(self.sets.get(key, set()))

    def delete(self, *keys: str):
        removed = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                removed += 1
            if key in self.sets:
                del self.sets[key]
                removed += 1
            self.ttls.pop(key, None)
        return removed

    def expire(self, key: str, ttl: int):
        self.ttls[key] = ttl
        return True

    def pipeline(self):
        return _FakePipeline(self)

    def close(self):
        return None


def _sample_payload() -> RecommendationResponse:
    return RecommendationResponse(
        generated_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        summary=RecommendationSummary(habit_score=72.5, goals_count=1),
        insights=["Stay consistent"],
        recommendations=[
            RecommendationItem(
                id="sleep-set-wake-goal",
                category=RecommendationCategory.SLEEP,
                priority=RecommendationPriority.HIGH,
                title="Set a wake goal",
                detail="Pick a preferred wake time",
                confidence=0.9,
            )
        ],
        by_category={"sleep": []},
        daily_plan=DailyPlan(morning_focus="Wake on time"),
    )


@pytest.fixture
def fake_redis():
    reset_redis_client()
    client = _FakeRedis()
    with patch("app.core.redis_client.get_redis", return_value=client), patch(
        "app.services.recommendation_cache.get_redis", return_value=client
    ):
        yield client
    reset_redis_client()


def _ensure_profile(db_session, user, **kwargs) -> UserProfile:
    profile = db_session.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if profile is None:
        profile = UserProfile(user_id=user.id, sleep_duration_hours=8.0, timezone="UTC")
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)
    for key, value in kwargs.items():
        setattr(profile, key, value)
    db_session.commit()
    db_session.refresh(profile)
    return profile


class TestRecommendationCacheUnit:
    def test_set_get_roundtrip(self, fake_redis):
        payload = _sample_payload()
        assert RecommendationCache.set(42, payload) is True
        cached = RecommendationCache.get(42)
        assert cached is not None
        assert cached.summary.habit_score == 72.5
        assert cached.recommendations[0].id == "sleep-set-wake-goal"
        assert fake_redis.ttls  # TTL applied

    def test_variant_keys_are_isolated(self, fake_redis):
        full = _sample_payload()
        limited = _sample_payload()
        limited.summary.habit_score = 10.0
        RecommendationCache.set(1, full)
        RecommendationCache.set(1, limited, limit=2)
        assert RecommendationCache.get(1).summary.habit_score == 72.5
        assert RecommendationCache.get(1, limit=2).summary.habit_score == 10.0

    def test_invalidate_clears_all_user_variants(self, fake_redis):
        RecommendationCache.set(7, _sample_payload())
        RecommendationCache.set(7, _sample_payload(), digest=True)
        RecommendationCache.set(7, _sample_payload(), limit=3)
        RecommendationCache.invalidate_user(7)
        assert RecommendationCache.get(7) is None
        assert RecommendationCache.get(7, digest=True) is None
        assert RecommendationCache.get(7, limit=3) is None

    def test_redis_errors_are_soft_failures(self, fake_redis):
        fake_redis.fail_next = True
        assert RecommendationCache.get(1) is None
        assert RecommendationCache.set(1, _sample_payload()) is False
        RecommendationCache.invalidate_user(1)  # must not raise


class TestRecommendationServiceCaching:
    def test_second_call_serves_cache_without_recompute(
        self, fake_redis, db_session, test_user
    ):
        _ensure_profile(db_session, test_user)
        db_session.refresh(test_user)

        with patch.object(
            RecommendationService,
            "_compute_recommendations",
            wraps=RecommendationService._compute_recommendations,
        ) as compute:
            first = RecommendationService.generate_recommendations(
                test_user, db_session
            )
            second = RecommendationService.generate_recommendations(
                test_user, db_session
            )

        assert compute.call_count == 1
        assert first.generated_at == second.generated_at
        assert [r.id for r in first.recommendations] == [
            r.id for r in second.recommendations
        ]

    def test_invalidate_forces_recompute(self, fake_redis, db_session, test_user):
        _ensure_profile(db_session, test_user)
        db_session.refresh(test_user)

        RecommendationService.generate_recommendations(test_user, db_session)
        RecommendationCache.invalidate_user(test_user.id)

        with patch.object(
            RecommendationService,
            "_compute_recommendations",
            wraps=RecommendationService._compute_recommendations,
        ) as compute:
            RecommendationService.generate_recommendations(test_user, db_session)

        assert compute.call_count == 1

    def test_unavailable_redis_still_returns_recommendations(
        self, db_session, test_user
    ):
        reset_redis_client()
        _ensure_profile(db_session, test_user)
        db_session.refresh(test_user)

        with patch(
            "app.services.recommendation_cache.get_redis", return_value=None
        ), patch(
            "app.core.redis_client.get_redis", return_value=None
        ):
            result = RecommendationService.generate_recommendations(
                test_user, db_session
            )

        assert result.recommendations
        assert result.summary is not None
