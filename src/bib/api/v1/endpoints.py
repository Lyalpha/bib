"""API v1 endpoint registrations (filled in incrementally)."""

from __future__ import annotations

from bib import __version__
from bib.api.v1 import router


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "version": __version__}
