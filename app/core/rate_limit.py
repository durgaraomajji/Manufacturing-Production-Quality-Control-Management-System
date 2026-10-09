"""Simple in-memory sliding-window rate limiter.

Fine for a single process. For multi-worker deployments back `RateLimiter` with Redis
(INCR + EXPIRE) - the interface (`hit`) stays the same.
"""
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import RateLimitError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Register a request. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False, max(int(window_seconds - (now - q[0])) + 1, 1)
            q.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global per-client request limit."""

    def __init__(self, app, limit: int | None = None, enabled: bool | None = None):
        super().__init__(app)
        self.limit = limit if limit is not None else settings.RATE_LIMIT_PER_MINUTE
        self.enabled = settings.RATE_LIMIT_ENABLED if enabled is None else enabled
        self.limiter = RateLimiter()

    async def dispatch(self, request: Request, call_next):
        if self.enabled and request.url.path not in ("/health", "/docs", "/openapi.json", "/redoc"):
            allowed, retry = self.limiter.hit(f"global:{_client_key(request)}", self.limit)
            if not allowed:
                return JSONResponse(
                    {"error": {"code": "rate_limited", "message": "Too many requests", "details": {"retry_after": retry}}},
                    status_code=429, headers={"Retry-After": str(retry)},
                )
        return await call_next(request)


def login_rate_limit(request: Request) -> None:
    """FastAPI dependency: stricter limit on credential endpoints (brute-force protection)."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    allowed, retry = limiter.hit(f"login:{_client_key(request)}", settings.LOGIN_RATE_LIMIT_PER_MINUTE)
    if not allowed:
        raise RateLimitError("Too many attempts, try again later", details={"retry_after": retry})
