"""Structured export: population selectors in, downloadable tables out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from bib.api.v1.pipeline import IGM_PARAM_PATTERN
from bib.db.session import get_db
from bib.export.build import build_export
from bib.export.catalog import EXPORT_FORMATS, EXPORT_UNITS, PRODUCTS, product_options
from bib.export.formats import render_export
from bib.science import redshift as zlib

router = APIRouter()

_PRODUCT_KEYS = "|".join(PRODUCTS)


@router.get("/export/options", summary="Export products, units and formats")
def export_options() -> dict:
    """Catalogue for the request-data page. Add a product in ``bib.export.catalog``."""
    return {
        "products": product_options(),
        "units": list(EXPORT_UNITS),
        "formats": list(EXPORT_FORMATS),
    }


@router.get("/export", summary="Download a structured SSP table")
def export_data(
    product: str = Query(..., pattern=f"^({_PRODUCT_KEYS})$"),
    release: str | None = None,
    imf: str | None = None,
    z_label: str | None = None,
    pop_type: str | None = Query(None, pattern="^(bin|sin)$"),
    alpha_label: str | None = None,
    all_z: bool = Query(False, description="Every loaded metallicity for this IMF / type"),
    log_age: float | None = Query(None, ge=6.0, le=11.0),
    all_ages: bool = False,
    units: str = Query("native", pattern="^(native|physical)$"),
    mass: float = Query(1.0, gt=0, description="Formed mass in Msun; used only for physical units"),
    dust_law: str | None = None,
    ebv: float = Query(0.0, ge=0.0, le=5.0),
    rv: float | None = Query(None, ge=2.0, le=6.0, description="R_V for CCM89/F99 (2.0–6.0)"),
    redshift: float = Query(0.0, ge=0.0, le=zlib.MAX_REDSHIFT),
    igm: str = Query(
        "none",
        pattern=IGM_PARAM_PATTERN,
        description="IGM attenuation (SED / photometry, observer frame, redshift > 0)",
    ),
    filters: str | None = Query(None, description="Comma-separated filter names (photometry)"),
    format: str = Query("csv", pattern="^(json|csv|ecsv|ascii)$"),
    db: Session = Depends(get_db),
):
    """Build a download from IMF / Z / age selectors — no population_id required.

    ``units=native`` is the BPASS 10^6 M☉ published scale. ``units=physical``
    scales extensive quantities to ``mass`` (default 1 M☉) and converts
    logarithmic columns to linear values. Every file states the query, units
    and column descriptions in its header.
    """
    if not all_z and not z_label:
        raise HTTPException(422, "set z_label or all_z")
    if not all_ages and log_age is None:
        raise HTTPException(422, "set log_age or all_ages")
    table = build_export(
        db,
        product=product,
        release=release,
        imf=imf,
        z_label=z_label,
        pop_type=pop_type,
        alpha_label=alpha_label,
        all_z=all_z,
        log_age=log_age,
        all_ages=all_ages,
        units=units,
        mass=mass,
        dust_law=dust_law,
        ebv=ebv,
        rv=rv,
        redshift=redshift,
        igm=igm,
        filters=filters,
        fmt=format,
    )
    return render_export(table, format)
