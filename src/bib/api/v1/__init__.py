"""REST API v1.

The API is the foundation for the future generic query builder: everything the
web UI renders is fetched from these endpoints, so any analysis available in
the browser is scriptable too.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["bib API v1"])

from bib.api.v1 import endpoints as _endpoints  # noqa: E402,F401  (registers routes)
