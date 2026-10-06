"""Small in-memory rate limiter for single-process development deployments."""
from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic
from typing import Deque

from fastapi import HTTPException, Request, status

from backend.core.config import settings

_buckets: dict[str, Deque[float]] = defaultdict(deque)


def check_rate_limit(request: Request, name: str, limit: int, window_seconds: int) -> None:
    """Raise 429 when a client exceeds a named request limit."""
    if not settings.rate_limit_enabled:
        return

    client = request.client.host if request.client else "unknown"
    key = f"{name}:{client}"
    now = monotonic()
    bucket = _buckets[key]

    while bucket and now - bucket[0] >= window_seconds:
        bucket.popleft()

    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait and try again.",
            headers={"Retry-After": str(window_seconds)},
        )

    bucket.append(now)


def login_rate_limit(request: Request) -> None:
    check_rate_limit(request, "auth-login", settings.rate_limit_login_per_minute, 60)


def register_rate_limit(request: Request) -> None:
    check_rate_limit(request, "auth-register", settings.rate_limit_register_per_hour, 3600)


def expensive_api_rate_limit(request: Request) -> None:
    check_rate_limit(request, "expensive-api", settings.rate_limit_expensive_per_minute, 60)
