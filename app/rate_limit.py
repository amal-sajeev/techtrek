"""Lightweight in-memory rate limiter (no external dependencies)."""
import functools
import time
from collections import defaultdict
from threading import Lock


class _RateLimiter:
    """Thread-safe sliding-window rate limiter keyed by client IP."""

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _is_allowed(self, key: str, max_calls: int, period: int) -> bool:
        now = time.monotonic()
        with self._lock:
            timestamps = self._windows[key]
            cutoff = now - period
            self._windows[key] = [t for t in timestamps if t > cutoff]
            if len(self._windows[key]) >= max_calls:
                return False
            self._windows[key].append(now)
            return True

    def limit(self, rate_string: str):
        """Decorator factory. `rate_string` is e.g. '10/minute', '5/minute'."""
        count_str, _, unit = rate_string.partition("/")
        max_calls = int(count_str)
        period = {"second": 1, "minute": 60, "hour": 3600}.get(unit, 60)

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                request = kwargs.get("request") or (args[0] if args else None)
                client_ip = "unknown"
                if request and hasattr(request, "client") and request.client:
                    client_ip = request.client.host
                key = f"{func.__module__}.{func.__qualname__}:{client_ip}"
                if not self._is_allowed(key, max_calls, period):
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        {"error": "Too many requests. Please try again later."},
                        status_code=429,
                    )
                return await func(*args, **kwargs)
            return wrapper
        return decorator


limiter = _RateLimiter()
