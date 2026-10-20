"""Low-cardinality Sentry metrics. No-ops when the SDK is missing or inactive."""

from __future__ import annotations

from bib.ops.stats import COUNTED_PATHS

_PROBES = frozenset({"/api/v1/health", "/api/v1/ready"})


def classify_route(path: str, admin_path: str = "/_ops") -> str:
    """Collapse request paths so metric attributes stay bounded."""
    if path.startswith("/static"):
        return "static"
    if path in COUNTED_PATHS or path in _PROBES or path == "/robots.txt":
        return path
    admin = (admin_path or "/_ops").rstrip("/") or "/_ops"
    if path == admin or path.startswith(f"{admin}/"):
        return "admin"
    if path.startswith("/api/"):
        return "api"
    return "other"


def emit_request(
    method: str, path: str, status: int, duration_s: float, admin_path: str = "/_ops"
) -> None:
    if path.startswith("/static"):
        return
    metrics = _metrics()
    if metrics is None:
        return
    route = classify_route(path, admin_path)
    attrs = {
        "route": route,
        "method": method,
        "status": f"{status // 100}xx",
    }
    try:
        metrics.count("bib.request", 1, attributes=attrs)
        metrics.distribution(
            "bib.request.duration",
            duration_s * 1000.0,
            unit="millisecond",
            attributes=attrs,
        )
        if status == 429:
            metrics.count("bib.ratelimit", 1, attributes={"route": route, "method": method})
    except Exception:
        return


def emit_page_hit(path: str) -> None:
    metrics = _metrics()
    if metrics is None:
        return
    try:
        metrics.count("bib.page_hit", 1, attributes={"path": path})
    except Exception:
        return


def _metrics():
    try:
        import sentry_sdk
        from sentry_sdk import metrics
    except ImportError:
        return None
    client = sentry_sdk.get_client()
    if not client.is_active():
        return None
    return metrics
