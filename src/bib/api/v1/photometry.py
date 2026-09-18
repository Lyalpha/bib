"""Synthetic photometry endpoints."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from bib.api.v1.helpers import get_population_or_404, resolve_age_index
from bib.db import models as m
from bib.db.session import get_db
from bib.science import redshift as zlib
from bib.science import sed as sedlib
from bib.science.dust import DUST_LAWS, apply_dust
from bib.science.filters import get_curves
from bib.science.photometry import (
    AB_ZERO_FNU,
    C_A_S,
    FilterCurve,
    ab_magnitude,
    parse_custom_filter,
)

router = APIRouter()

MAX_UPLOAD_BYTES = 1 << 20  # 1 MiB is plenty for a transmission curve
_UPLOAD_CHUNK = 64 * 1024


def sanitize_upload_name(name: str | None) -> str:
    base = Path(name or "custom").name
    cleaned = "".join(c for c in base if c.isprintable() and c not in "<>&\"'`")
    return cleaned.strip()[:80] or "custom"


async def read_upload_capped(file: UploadFile, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "filter file too large (max 1 MiB)")
        chunks.append(chunk)
    return b"".join(chunks)


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


def _observe(
    wavelength: np.ndarray, flux: np.ndarray, z: float
) -> tuple[np.ndarray, np.ndarray]:
    """Rest L_sun/Å -> observer-frame f_λ (cgs). z=0 means 'at 10 pc'."""
    return zlib.observe(wavelength, flux, z)


def _photometry_payload(
    wl_obs: np.ndarray,
    flam_cgs: np.ndarray,
    curves: list[FilterCurve],
    z: float,
) -> list[dict]:
    out = []
    for curve in curves:
        result = ab_magnitude(wl_obs, flam_cgs, curve, flux_unit="flam_cgs")
        entry = {
            "filter": curve.name,
            "display_name": curve.display_name,
            "group": curve.group,
            "detector_type": curve.detector_type,
            "lambda_eff": result.lambda_eff,
            "ab_mag": None if result.ab_mag is None else round(result.ab_mag, 4),
            "coverage": round(result.coverage, 3),
            "plot_level": None,
        }
        if result.ab_mag is not None:
            # The measured magnitude as a point on the SED Explorer's curve:
            # f_ν(m_AB) -> f_λ at the pivot wavelength -> plot units.
            f_nu = AB_ZERO_FNU * 10.0 ** (-0.4 * result.ab_mag)
            f_lam_pivot = f_nu * C_A_S / result.lambda_eff**2
            entry["plot_level"] = float(zlib.plot_level_lsun_a(f_lam_pivot, z))
        out.append(entry)
    return out


def _frame_info(z: float) -> dict:
    return {
        "redshift": z,
        "frame": "apparent" if z > 0 else "absolute (10 pc)",
        "luminosity_distance_mpc": zlib.luminosity_distance_mpc(z),
        "cosmology": zlib.COSMOLOGY_LABEL if z > 0 else None,
    }


@router.get("/photometry", summary="AB magnitudes through bundled filters")
def get_photometry(
    population_id: int,
    log_age: float | None = Query(
        None,
        ge=6.0,
        le=11.0,
        description="log10(age/yr) on the BPASS 0.1 dex grid (6.0–11.0). Prefer this over age_index.",
    ),
    age_index: int | None = Query(
        None, ge=0, le=50, description="0–50 grid index; prefer log_age"
    ),
    filters: str | None = Query(None, description="Comma-separated filter names (default: all)"),
    mass: float = Query(1e6, gt=0),
    dust_law: str | None = None,
    ebv: float = Query(0.0, ge=0.0, le=5.0),
    rv: float | None = Query(None, gt=1.0, lt=10.0),
    redshift: float = Query(0.0, ge=0.0, le=zlib.MAX_REDSHIFT),
    db: Session = Depends(get_db),
) -> dict:
    """AB magnitudes of the population SED through bundled filters.

    ``log_age`` is log10(age/yr) on BPASS's 0.1 dex grid (6.0 = 1 Myr … 11.0 =
    100 Gyr). ``redshift=0`` (default): absolute magnitudes, source at 10 pc.
    ``redshift>0``: apparent magnitudes — the SED is shifted to the observer
    frame at the luminosity distance of the given z (flat ΛCDM, H0=70,
    Ωm=0.3) and convolved there, so K-corrections are included naturally.
    Dust (if any) is applied in the rest frame. Computed on the
    full-resolution SED; magnitudes scale with ``mass`` (BPASS native:
    10^6 Msun formed).
    """
    age_index = resolve_age_index(age_index, log_age)
    wavelength, flux, sed = _native_sed(db, population_id, age_index)
    flux, dust_info = _transform(wavelength, flux, mass, dust_law, ebv, rv)
    wl_obs, flam = _observe(wavelength, flux, redshift)
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
        **_frame_info(redshift),
        "photometry": _photometry_payload(wl_obs, flam, curves, redshift),
    }


@router.post("/photometry/custom", summary="AB magnitude through an uploaded filter curve")
async def post_custom_photometry(
    file: UploadFile = File(..., description="Two-column ASCII: wavelength [Å], transmission"),
    population_id: int = Form(...),
    log_age: float | None = Form(None, description="log10(age/yr) on the 0.1 dex grid 6.0–11.0"),
    age_index: int | None = Form(None, ge=0, le=50),
    mass: float = Form(1e6, gt=0),
    dust_law: str | None = Form(None),
    ebv: float = Form(0.0, ge=0.0, le=5.0),
    rv: float | None = Form(None),
    redshift: float = Form(0.0, ge=0.0, le=zlib.MAX_REDSHIFT),
    db: Session = Depends(get_db),
) -> dict:
    """Upload a transmission curve, get the AB magnitude plus the parsed curve back."""
    age_index = resolve_age_index(age_index, log_age)
    raw = await read_upload_capped(file)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "filter file must be ASCII/UTF-8 text") from exc
    try:
        curve = parse_custom_filter(text, name=sanitize_upload_name(file.filename))
    except ValueError as exc:
        raise HTTPException(422, f"could not parse filter: {exc}") from exc

    wavelength, flux, sed = _native_sed(db, population_id, age_index)
    flux, dust_info = _transform(wavelength, flux, mass, dust_law, ebv, rv)
    wl_obs, flam = _observe(wavelength, flux, redshift)
    payload = _photometry_payload(wl_obs, flam, [curve], redshift)[0]
    step = max(1, curve.wavelength.size // 500)
    return {
        "population_id": population_id,
        "age_index": age_index,
        "log_age": sed.log_age,
        "mass": mass,
        "dust": dust_info,
        **_frame_info(redshift),
        "result": payload,
        "curve_preview": {
            "wavelength": [float(v) for v in curve.wavelength[::step]],
            "transmission": [float(v) for v in curve.transmission[::step]],
        },
    }
