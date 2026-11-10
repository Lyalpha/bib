"""Security headers applied to every response."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

# FastAPI's Swagger/ReDoc pages load jsDelivr assets and a small inline bootstrap.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _csp_for(path: str) -> str:
    if path.startswith("/api/docs") or path.startswith("/api/redoc"):
        return _DOCS_CSP
    return CSP


def allow_goatcounter(csp: str, origin: str | None) -> str:
    """Permit the GoatCounter pixel host when an endpoint is configured."""
    if not origin:
        return csp
    csp = csp.replace("connect-src 'self';", f"connect-src 'self' {origin};", 1)
    csp = csp.replace("img-src 'self' data:", f"img-src 'self' data: {origin}", 1)
    return csp


def csp_header(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    origin = settings.goatcounter_origin if settings else None
    return allow_goatcounter(_csp_for(request.url.path), origin)


def apply_security_headers(response: Response, request: Request, request_id: str) -> None:
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = csp_header(request)
