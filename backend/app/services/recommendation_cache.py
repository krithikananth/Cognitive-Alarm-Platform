"""
Recommendation result cache backed by Redis.

Caches serialized ``RecommendationResponse`` payloads so repeated reads avoid
recomputing signals. All Redis errors are swallowed — callers must treat cache
misses and Redis outages the same way (recompute).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.core.config import settings
from app.core.redis_client import get_redis
from app.schemas.recommendation import RecommendationCategory, RecommendationResponse

logger = logging.getLogger(__name__)

_KEY_PREFIX = "icap:v1:recs"
_INDEX_PREFIX = "icap:v1:recs:index"


class RecommendationCache:
    """Get / set / invalidate recommendation payloads per user."""

    @staticmethod
    def _variant_key(
        categories: Optional[List[RecommendationCategory]],
        limit: Optional[int],
        *,
        digest: bool = False,
    ) -> str:
        if digest:
            return "digest"
        if categories:
            cats = ",".join(sorted(c.value for c in categories))
        else:
            cats = "all"
        lim = "all" if limit is None else str(limit)
        return f"q:{cats}:{lim}"

    @staticmethod
    def _payload_key(user_id: int, variant: str) -> str:
        return f"{_KEY_PREFIX}:{user_id}:{variant}"

    @staticmethod
    def _index_key(user_id: int) -> str:
        return f"{_INDEX_PREFIX}:{user_id}"

    @classmethod
    def get(
        cls,
        user_id: int,
        *,
        categories: Optional[List[RecommendationCategory]] = None,
        limit: Optional[int] = None,
        digest: bool = False,
    ) -> Optional[RecommendationResponse]:
        """Return a cached response, or ``None`` on miss / Redis failure."""
        client = get_redis()
        if client is None:
            return None

        key = cls._payload_key(
            user_id, cls._variant_key(categories, limit, digest=digest)
        )
        try:
            raw = client.get(key)
            if not raw:
                return None
            return RecommendationResponse.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 — soft-fail cache
            logger.warning("Recommendation cache get failed for user %s: %s", user_id, exc)
            return None

    @classmethod
    def set(
        cls,
        user_id: int,
        payload: RecommendationResponse,
        *,
        categories: Optional[List[RecommendationCategory]] = None,
        limit: Optional[int] = None,
        digest: bool = False,
    ) -> bool:
        """Store a recommendation payload. Returns True on success."""
        client = get_redis()
        if client is None:
            return False

        variant = cls._variant_key(categories, limit, digest=digest)
        key = cls._payload_key(user_id, variant)
        index_key = cls._index_key(user_id)
        ttl = max(1, int(settings.RECOMMENDATION_CACHE_TTL_SECONDS))

        try:
            pipe = client.pipeline()
            pipe.set(key, payload.model_dump_json(), ex=ttl)
            pipe.sadd(index_key, key)
            pipe.expire(index_key, ttl)
            pipe.execute()
            return True
        except Exception as exc:  # noqa: BLE001 — soft-fail cache
            logger.warning("Recommendation cache set failed for user %s: %s", user_id, exc)
            return False

    @classmethod
    def invalidate_user(cls, user_id: int) -> None:
        """Drop all cached recommendation variants for a user.

        Safe to call when Redis is down — no-ops on failure.
        """
        client = get_redis()
        if client is None:
            return

        index_key = cls._index_key(user_id)
        try:
            keys = list(client.smembers(index_key) or [])
            if keys:
                client.delete(*keys)
            client.delete(index_key)
        except Exception as exc:  # noqa: BLE001 — soft-fail cache
            logger.warning(
                "Recommendation cache invalidate failed for user %s: %s", user_id, exc
            )
