"""In-process token bucket for expensive routes (one bucket per client IP)."""

from __future__ import annotations

import re
import threading
import time

from starlette.requests import Request

from bib.config import Settings

_SED = re.compile(r"^/api/v1/populations/\d+/sed$")


def client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def is_limited(request: Request, settings: Settings) -> bool:
    path = request.url.path
    method = request.method
    admin = settings.normalized_admin_path
    if method == "POST" and path == "/api/v1/photometry/custom":
        return True
    if method == "POST" and path.rstrip("/") == f"{admin}/login":
        return True
    if method != "GET":
        return False
    if path == "/api/v1/photometry":
        return True
    if path.endswith("/sed_frames"):
        return True
    if _SED.match(path):
        query = request.query_params
        return query.get("resolution") == "native" or query.get("format") == "csv"
    return False


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.rate = max(1, per_minute) / 60.0
        self.burst = max(1, per_minute)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.burst), now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            allowed = tokens >= 1.0
            self._state[key] = (tokens - 1.0 if allowed else tokens, now)
            if len(self._state) > 8000:
                stale = [k for k, (t, ts) in self._state.items() if now - ts > 300 and t >= self.burst]
                for k in stale[:4000]:
                    del self._state[k]
            return allowed
