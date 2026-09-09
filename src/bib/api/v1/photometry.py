"""Synthetic photometry endpoints."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from bib.api.v1.helpers import get_population_or_404
from bib.db import models as m
from bib.db.session import get_db
from bib.science import sed as sedlib
from bib.science.dust import DUST_LAWS, apply_dust
from bib.science.filters import get_curves
from bib.science.photometry import FilterCurve, ab_magnitude, parse_custom_filter

router = APIRouter()

MAX_UPLOAD_BYTES = 1 << 20  # 1 MiB is plenty for a transmission curve


def _native_sed(
    db: Session, population_id: int, age_index: int
) -> tuple[np.ndarray, np.ndarray, m.Sed]:
    population = get_population_or_404(db, population_id)
    sed = db.get(m.Sed, {"population_id": population_id, "age_index": age_index})
    if sed is None:
        raise HTTPException(404, f"no SED at age_index {age_index}")
    grid = db.get(m.WavelengthGrid, population.native_grid_id)
    wavelength = sedlib.decode_f64(grid.data, grid.n_points)
    flux = sedlib.decode_f32(sed.flux, sed.n_points)
    return wavelength, flux, sed


def _transform(
    wavelength: np.ndarray,
    flux: np.ndarray,
    mass: float,
    dust_law: str | None,
    ebv: float,
    rv: float | None,
) -> tuple[np.ndarray, dict | None]:
    flux = sedlib.scale_by_mass(flux, mass)
    dust_info = None
    if dust_law and ebv > 0:
        if dust_law not in DUST_LAWS:
            raise HTTPException(422, f"unknown dust law '{dust_law}'")
        result = apply_dust(wavelength, flux, dust_law, ebv, rv)
        flux, dust_info = result.flux, {
            "law": dust_law, "ebv": ebv, "rv": result.rv, "a_v": result.a_v,
            "applied_range_a": list(result.applied_range_a),
        }
    return flux, dust_info


def _photometry_payload(
    wavelength: np.ndarray,
    flux: np.ndarray,
    curves: list[FilterCurve],
) -> list[dict]:
    out = []
    for curve in curves:
        result = ab_magnitude(wavelength, flux, curve)
        out.append(
            {
                "filter": curve.name,
                "display_name": curve.display_name,
                "group": curve.group,
                "detector_type": curve.detector_type,
                "lambda_eff": result.lambda_eff,
                "ab_mag": None if result.ab_mag is None else round(result.ab_mag, 4),
                "coverage": round(result.coverage, 3),
            }
        )
    return out


@router.get("/photometry", summary="Absolute AB magnitudes through bundled filters")
def get_photometry(
    population_id: int,
    age_index: int = Query(ge=0, le=50),
    filters: str | None = Query(None, description="Comma-separated filter names (default: all)"),
    mass: float = Query(1e6, gt=0),
    dust_law: str | None = None,
    ebv: float = Query(0.0, ge=0.0, le=5.0),
    rv: float | None = Query(None, gt=1.0, lt=10.0),
    db: Session = Depends(get_db),
) -> dict:
    """AB magnitudes of the population SED (10 pc absolute convention).

    Computed on the full-resolution SED. Magnitudes scale with ``mass``:
    the default is the BPASS-native 10^6 Msun formed.
    """
    wavelength, flux, sed = _native_sed(db, population_id, age_index)
    flux, dust_info = _transform(wavelength, flux, mass, dust_law, ebv, rv)
    names = [n.strip() for n in filters.split(",") if n.strip()] if filters else None
    curves = get_curves(db, names)
    if names and len(curves) != len(names):
        missing = set(names) - {c.name for c in curves}
        raise HTTPException(404, f"unknown filters: {sorted(missing)}")
    return {
        "population_id": population_id,
        "age_index": age_index,
        "log_age": sed.log_age,
        "mass": mass,
        "dust": dust_info,
        "note": "Absolute AB magnitudes (source at 10 pc).",
        "photometry": _photometry_payload(wavelength, flux, curves),
    }


@router.post("/photometry/custom", summary="AB magnitude through an uploaded filter curve")
async def post_custom_photometry(
    file: UploadFile = File(..., description="Two-column ASCII: wavelength [Å], transmission"),
    population_id: int = Form(...),
    age_index: int = Form(..., ge=0, le=50),
    mass: float = Form(1e6, gt=0),
    dust_law: str | None = Form(None),
    ebv: float = Form(0.0, ge=0.0, le=5.0),
    rv: float | None = Form(None),
    db: Session = Depends(get_db),
) -> dict:
    """Upload a transmission curve, get the AB magnitude plus the parsed curve back."""
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "filter file too large (max 1 MiB)")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "filter file must be ASCII/UTF-8 text") from exc
    try:
        curve = parse_custom_filter(text, name=file.filename or "custom")
    except ValueError as exc:
        raise HTTPException(422, f"could not parse filter: {exc}") from exc

    wavelength, flux, sed = _native_sed(db, population_id, age_index)
    flux, dust_info = _transform(wavelength, flux, mass, dust_law, ebv, rv)
    payload = _photometry_payload(wavelength, flux, [curve])[0]
    step = max(1, curve.wavelength.size // 500)
    return {
        "population_id": population_id,
        "age_index": age_index,
        "log_age": sed.log_age,
        "mass": mass,
        "dust": dust_info,
        "result": payload,
        "curve_preview": {
            "wavelength": [float(v) for v in curve.wavelength[::step]],
            "transmission": [float(v) for v in curve.transmission[::step]],
        },
    }
