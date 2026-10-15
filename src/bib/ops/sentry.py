"""Optional Sentry / GlitchTip hook. Import sentry_sdk only when a DSN is set."""

from __future__ import annotations

import logging
from typing import Any

from bib import __version__
from bib.config import Settings

log = logging.getLogger("bib.ops.sentry")

ADMIN_COOKIE = "bib_ops"


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in {"authorization", "cookie", "set-cookie"}:
                    headers[key] = "[filtered]"
        cookies = request.get("cookies")
        if isinstance(cookies, dict) and ADMIN_COOKIE in cookies:
            cookies[ADMIN_COOKIE] = "[filtered]"
    return event


def init_sentry(settings: Settings) -> None:
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        log.warning("BIB_SENTRY_DSN is set but sentry-sdk is not installed")
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment_name,
        release=f"bib@{__version__}",
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=0,
        before_send=_scrub_event,
    )
    log.info("Sentry error reporting and metrics enabled")
