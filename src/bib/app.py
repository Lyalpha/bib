"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bib import __version__
from bib.config import get_branding, get_settings

_WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app() -> FastAPI:
    settings = get_settings()
    branding = get_branding()

    app = FastAPI(
        title=f"{branding.site_name} — {branding.full_name}",
        version=__version__,
        description=(
            "A pedagogical explorer and lightweight analysis interface for BPASS "
            "stellar population synthesis results. REST API documented below; "
            "interactive pages served at `/`."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        debug=settings.debug,
    )

    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")

    from bib.api.v1 import router as api_v1_router
    from bib.web.routes import router as web_router

    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(web_router)

    return app
