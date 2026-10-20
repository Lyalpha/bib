"""Production-ops middleware: logs, headers, rate limits, visit counts."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from bib.config import Settings
from bib.ops.headers import apply_security_headers
from bib.ops.logging import LogRing, setup_logging
from bib.ops.metrics import emit_request
from bib.ops.ratelimit import RateLimiter, client_ip, is_limited
from bib.ops.robots import router as robots_router
from bib.ops.stats import PathCounter, maybe_record, start_flusher

__all__ = ["LogRing", "PathCounter", "install", "start_flusher"]


def install(app: FastAPI, settings: Settings) -> None:
    ring: LogRing = app.state.log_ring
    logger = setup_logging(settings, ring)
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.stats = PathCounter()
    app.include_router(robots_router)

    @app.middleware("http")
    async def ops_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        if is_limited(request, settings) and not app.state.rate_limiter.allow(client_ip(request)):
            response = JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
            response.headers["Retry-After"] = "60"
            apply_security_headers(response, request, request_id)
            _log_request(logger, request, 429, 0.0, request_id)
            emit_request(request.method, request.url.path, 429, 0.0, settings.normalized_admin_path)
            return response

        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            dt = time.perf_counter() - t0
            logger.exception(
                "request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "duration_ms": round(dt * 1000, 2),
                },
            )
            emit_request(request.method, request.url.path, 500, dt, settings.normalized_admin_path)
            raise
        dt = time.perf_counter() - t0
        apply_security_headers(response, request, request_id)
        _log_request(logger, request, response.status_code, dt, request_id)
        emit_request(
            request.method,
            request.url.path,
            response.status_code,
            dt,
            settings.normalized_admin_path,
        )
        maybe_record(request, response)
        return response


def _log_request(
    logger: logging.Logger, request: Request, status: int, dt: float, request_id: str
) -> None:
    path = request.url.path
    if path.startswith("/static"):
        return
    extra = {
        "request_id": request_id,
        "method": request.method,
        "path": path,
        "status": status,
        "duration_ms": round(dt * 1000, 2),
    }
    if status >= 500:
        logger.error("request", extra=extra)
    elif status >= 400:
        logger.warning("request", extra=extra)
    else:
        logger.info("request", extra=extra)
