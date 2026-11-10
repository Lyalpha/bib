"""Jinja2 template environment with branding and site-wide context."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from bib import __version__
from bib.config import get_branding

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Cached "is any synthetic data loaded?" flag: (value, expiry_timestamp).
_synthetic_cache: tuple[bool, float] = (False, 0.0)
_SYNTHETIC_TTL_S = 30.0


def has_synthetic_data() -> bool:
    """True if any synthetic (demo) population or model is in the database.

    Cached briefly; returns False when the database is unreachable so page
    rendering never depends on DB availability.
    """
    global _synthetic_cache
    value, expiry = _synthetic_cache
    now = time.monotonic()
    if now < expiry:
        return value
    try:
        from sqlalchemy import text

        from bib.db.session import get_engine

        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM population WHERE is_synthetic) "
                    "OR EXISTS (SELECT 1 FROM stellar_model WHERE is_synthetic)"
                )
            ).scalar()
        value = bool(row)
    except Exception:
        value = False
    _synthetic_cache = (value, now + _SYNTHETIC_TTL_S)
    return value


def invalidate_synthetic_cache() -> None:
    global _synthetic_cache
    _synthetic_cache = (False, 0.0)


def _site_context(request: Request) -> dict[str, Any]:
    settings = getattr(request.app.state, "settings", None)
    return {
        "active_path": request.url.path,
        "has_synthetic": has_synthetic_data(),
        "expose_docs": bool(settings and settings.should_expose_docs),
        "goatcounter_endpoint": settings.goatcounter_endpoint if settings else None,
    }


templates = Jinja2Templates(directory=str(_TEMPLATE_DIR), context_processors=[_site_context])
templates.env.globals.update(
    branding=get_branding(),
    brand_css=get_branding().css_variables(),
    version=__version__,
)
