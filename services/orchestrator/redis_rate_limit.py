"""Redis-backed distributed rate limiting for the orchestrator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - optional dependency
    redis = None

from fastapi import HTTPException


@dataclass(slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int


class DistributedRateLimiter:
    def __init__(self, redis_url: Optional[str], limit_per_minute: int):
        self.redis_url = redis_url
        self.limit_per_minute = limit_per_minute
        self._client = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if not self.redis_url or redis is None:
            return

        self._client = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
        try:
            await self._client.ping()
        except Exception:
            self._client = None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def check(self, key: str) -> RateLimitDecision:
        if self.limit_per_minute <= 0:
            return RateLimitDecision(allowed=True, retry_after=0)

        if self._client is None:
            return await self._check_local_fallback(key)

        redis_key = f"tarbar:rate:{key}"
        async with self._lock:
            current = await self._client.incr(redis_key)
            if current == 1:
                await self._client.expire(redis_key, 60)
            ttl = await self._client.ttl(redis_key)

        if current > self.limit_per_minute:
            return RateLimitDecision(allowed=False, retry_after=max(int(ttl), 1))
        return RateLimitDecision(allowed=True, retry_after=0)

    async def _check_local_fallback(self, key: str) -> RateLimitDecision:
        # Lightweight fallback keeps development/test runs functional when Redis is unavailable.
        if not hasattr(self, "_local_buckets"):
            self._local_buckets = {}  # type: ignore[attr-defined]

        now = asyncio.get_running_loop().time()
        window_start = now - 60.0
        bucket = self._local_buckets.setdefault(key, [])  # type: ignore[attr-defined]
        bucket[:] = [timestamp for timestamp in bucket if timestamp >= window_start]
        if len(bucket) >= self.limit_per_minute:
            retry_after = max(int(60 - (now - bucket[0])), 1)
            return RateLimitDecision(allowed=False, retry_after=retry_after)
        bucket.append(now)
        return RateLimitDecision(allowed=True, retry_after=0)

    async def enforce(self, key: str) -> None:
        decision = await self.check(key)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(decision.retry_after)},
            )
