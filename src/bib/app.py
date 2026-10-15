"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bib import __version__
from bib.config import get_branding, get_settings
from bib.ops import LogRing, install, start_flusher
from bib.ops.sentry import init_sentry
from bib.ops.stats import flush_stats

_WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = start_flusher(app)
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        flush_stats(app)


def create_app() -> FastAPI:
    settings = get_settings()
    init_sentry(settings)
    branding = get_branding()
    docs = (
        {"docs_url": "/api/docs", "redoc_url": "/api/redoc", "openapi_url": "/api/openapi.json"}
        if settings.should_expose_docs
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )

    app = FastAPI(
        title=f"{branding.site_name} — {branding.full_name}",
        version=__version__,
        description=(
            "A pedagogical explorer and lightweight analysis interface for BPASS "
            "stellar population synthesis results. REST API documented below; "
            "interactive pages served at `/`."
        ),
        debug=settings.debug,
        lifespan=lifespan,
        **docs,
    )
    app.state.settings = settings
    app.state.log_ring = LogRing()
    install(app, settings)
    if (settings.sentry_dsn or "").strip():
        import logging

        logging.getLogger("bib").info("Sentry error reporting enabled")

    if settings.allowed_host_list:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")

    from fastapi.responses import RedirectResponse

    from bib.api.v1 import router as api_v1_router
    from bib.web.routes import router as web_router

    docs_target = "/api/docs" if settings.should_expose_docs else "/data#api"

    async def api_docs_shortcut():
        """``/api`` and ``/api/v1`` are prefixes, not documents."""
        return RedirectResponse(docs_target, status_code=302)

    for path in ("/api", "/api/", "/api/v1", "/api/v1/"):
        app.add_api_route(path, api_docs_shortcut, methods=["GET"], include_in_schema=False)

    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(web_router)

    if settings.admin_token:
        from bib.web.admin import router as admin_router

        app.include_router(admin_router, prefix=settings.normalized_admin_path)

    return app
