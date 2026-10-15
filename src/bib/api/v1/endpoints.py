"""Basic service endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from bib import __version__

router = APIRouter()


def health_payload() -> dict:
    return {"status": "ok", "version": __version__}


def ready_payload() -> tuple[dict, int]:
    try:
        from sqlalchemy import text

        from bib.db.session import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return {"status": "unavailable"}, 503
    return {"status": "ok"}, 200


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    return health_payload()


@router.get("/ready", summary="Readiness probe")
async def ready():
    payload, status = ready_payload()
    if status != 200:
        return JSONResponse(payload, status_code=status)
    return payload
