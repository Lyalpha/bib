"""Basic service endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from bib import __version__

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "version": __version__}
