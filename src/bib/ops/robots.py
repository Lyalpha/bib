"""Dynamic robots.txt that never names the admin path."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(include_in_schema=False)


@router.get("/robots.txt")
def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /api/docs\nDisallow: /api/redoc\n")
