"""Redis-backed token-bucket rate limiting.

One Lua script does "refill + try to consume" atomically inside Redis, so concurrent
requests from the same identity can't race each other into double-spending tokens.
"""
import logging
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# KEYS[1]  = bucket's redis key
# ARGV[1]  = capacity            (max tokens / max burst)
# ARGV[2]  = refill_rate         (tokens added per second)
# ARGV[3]  = now                 (unix time, seconds, float)
# ARGV[4]  = requested           (tokens this request costs, normally 1)
#
# Returns: {allowed (0/1), tokens_remaining, retry_after_seconds}
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(bucket[1])
local last_ts = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_ts = now
end

local elapsed = math.max(0, now - last_ts)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
local retry_after = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    retry_after = (requested - tokens) / refill_rate
end

-- TTL: long enough that an idle bucket expires (frees memory) instead of living forever
local ttl = math.ceil(capacity / refill_rate) * 2
redis.call("HMSET", key, "tokens", tokens, "ts", now)
redis.call("EXPIRE", key, ttl)

return {allowed, tostring(tokens), tostring(retry_after)}
"""


class TokenBucket:
    """Thin wrapper that registers the Lua script once and evaluates it per call."""

    def __init__(self, redis_client: Redis):
        self._redis = redis_client
        self._script = redis_client.register_script(_TOKEN_BUCKET_LUA)

    async def consume(
        self, key: str, capacity: float, refill_rate: float, cost: float = 1.0
    ) -> tuple[bool, float, float]:
        """Returns (allowed, tokens_remaining, retry_after_seconds)."""
        allowed, tokens, retry_after = await self._script(
            keys=[key], args=[capacity, refill_rate, time.time(), cost]
        )
        return bool(int(allowed)), float(tokens), float(retry_after)


def get_client_ip(request: Request, trust_forwarded_for: bool) -> str:
    """
    The real client IP. Only trust X-Forwarded-For when the app sits behind a proxy that
    is guaranteed to set/overwrite it itself - otherwise a client can fake any IP it likes
    by sending that header directly, which would let it dodge rate limits entirely.
    """
    if trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # the header can be a comma-separated chain; the first entry is the original client
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _check(request: Request, name: str, capacity: float, refill_rate: float, identity: str) -> None:
    bucket: Optional[TokenBucket] = getattr(request.app.state, "rate_limiter", None)
    if bucket is None:
        # Redis/rate limiter not wired up (e.g. during certain tests) - fail open rather
        # than break the whole API; this should never happen in a real deployment.
        logger.warning("Rate limiter not configured; allowing request for %s.", name)
        return

    key = f"ratelimit:{name}:{identity}"
    try:
        allowed, _remaining, retry_after = await bucket.consume(key, capacity, refill_rate)
    except Exception:
        # Fail OPEN: a Redis blip must never block bookings/logins. We lose protection for
        # the duration of the outage, which is the right trade-off vs. an outage of our own.
        logger.exception("Rate limiter backend error for %s; allowing request.", name)
        return

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down and try again shortly.",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )


def rate_limit(name: str, capacity: float, refill_rate: float):
    """
    FastAPI dependency factory for IP-based limits (pre-auth endpoints: login, signup,
    public browsing).
      name:        short identifier for this limit, namespaces the Redis key
      capacity:    max burst size (tokens in a full bucket)
      refill_rate: tokens added per second
    """

    async def _dependency(request: Request) -> None:
        trust_xff: bool = getattr(request.app.state, "trust_x_forwarded_for", False)
        identity = f"ip:{get_client_ip(request, trust_xff)}"
        await _check(request, name, capacity, refill_rate, identity)

    return _dependency


def rate_limit_by_user(name: str, capacity: float, refill_rate: float, user_dependency):
    """
    FastAPI dependency factory for user-based limits (authenticated endpoints).

    `user_dependency` is the route's own auth dependency (e.g. `get_current_user`), passed
    in and re-declared with Depends() here too. FastAPI caches a dependency's result per
    request by the callable's identity, so this does NOT decode the JWT / hit the DB twice
    -- it reuses the same resolved user the route already required.
    """

    async def _dependency(request: Request, user=Depends(user_dependency)) -> None:
        await _check(request, name, capacity, refill_rate, f"user:{user.id}")

    return _dependency