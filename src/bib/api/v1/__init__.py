"""API v1: versioned REST interface consumed by the bib UI (and by you).

Interactive documentation: /api/docs (Swagger) and /api/redoc.
"""

from fastapi import APIRouter

router = APIRouter(tags=["v1"])  # mounted under /api/v1 by the app factory

from bib.api.v1 import (  # noqa: E402
    endpoints,
    export,
    filters,
    meta,
    photometry,
    populations,
)

router.include_router(endpoints.router)
router.include_router(meta.router)
router.include_router(populations.router)
router.include_router(filters.router)
router.include_router(photometry.router)
router.include_router(export.router)
