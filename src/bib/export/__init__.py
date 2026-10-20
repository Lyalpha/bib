"""Structured data export: tables with units, query metadata, and file formats.

The request-data page and ``GET /api/v1/export`` share this package. Add a
new SSP product here (catalog + builder) and the page picks it up.
"""

from bib.export.catalog import EXPORT_FORMATS, EXPORT_UNITS, PRODUCTS, product_options
from bib.export.formats import render_export
from bib.export.table import ExportTable

__all__ = [
    "EXPORT_FORMATS",
    "EXPORT_UNITS",
    "PRODUCTS",
    "ExportTable",
    "build_export",
    "find_populations",
    "product_options",
    "render_export",
]


def __getattr__(name: str):
    if name in {"build_export", "find_populations"}:
        from bib.export import build as _build

        return getattr(_build, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
