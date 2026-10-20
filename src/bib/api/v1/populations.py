"""Population endpoints: listing, SEDs, and per-age products."""

from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from bib.api.v1.helpers import (
    get_population_or_404,
    population_summary,
    resolve_age_index,
    sig_round,
)
from bib.api.v1.pipeline import IGM_PARAM_PATTERN, run_pipeline
from bib.db import models as m
from bib.db.session import get_db
from bib.science import redshift as zlib
from bib.science import sed as sedlib
from bib.science.igm import IGM_MODELS, igm_info, igm_transmission

router = APIRouter()

_TIMESERIES_TABLES: dict[str, tuple[type, list[str]]] = {
    "colours": (
        m.Colours,
        [
            "v_minus_i",
            "mag_u",
            "mag_b",
            "mag_v",
            "mag_r",
            "mag_i",
            "mag_j",
            "mag_h",
            "mag_k",
            "sdss_u",
            "sdss_g",
            "sdss_r",
            "sdss_i",
            "sdss_z",
            "f300w",
            "f336w",
            "f435w",
            "f450w",
            "f555w",
            "f606w",
            "f814w",
        ],
    ),
    "ionizing": (m.Ionizing, ["log_nion", "log_l_halpha", "log_l_fuv", "log_l_nuv"]),
    "starmass": (m.StarMass, ["mass_stars", "mass_remnants"]),
    "sn_rates": (
        m.SnRates,
        [
            "n_ia",
            "n_iip",
            "n_ii_other",
            "n_ib",
            "n_ic",
            "n_grb",
            "n_pisn",
            "n_low_mass",
            "bin_width_yr",
        ],
    ),
    "yields": (
        m.Yields,
        [
            "wind_h",
            "wind_he",
            "wind_z",
            "wind_energy",
            "sn_energy",
            "sn_h",
            "sn_he",
            "sn_z",
        ],
    ),
    "mlratio": (m.MLRatio, ["ml_k", "ml_v"]),
    "star_counts": (
        m.StarCounts,
        [
            "n_o_hi",
            "n_of_hi",
            "n_b_hi",
            "n_a_hi",
            "n_ysg_hi",
            "n_k_hi",
            "n_m_hi",
            "n_wnh_hi",
            "n_wn_hi",
            "n_wc_hi",
            "n_o_lo",
            "n_of_lo",
            "n_b_lo",
            "n_a_lo",
            "n_ysg_lo",
            "n_k_lo",
            "n_m_lo",
            "n_wnh_lo",
            "n_wn_lo",
            "n_wc_lo",
        ],
    ),
}


@router.get("/populations", summary="List populations (filterable)")
def list_populations(
    release: str | None = None,
    imf: str | None = None,
    z_label: str | None = None,
    pop_type: str | None = None,
    alpha_label: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(m.Population).options(joinedload(m.Population.release))
    if release:
        stmt = stmt.join(m.Release).where(m.Release.version == release)
    if imf:
        stmt = stmt.where(m.Population.imf == imf)
    if z_label:
        stmt = stmt.where(m.Population.z_label == z_label)
    if pop_type:
        stmt = stmt.where(m.Population.pop_type == pop_type)
    if alpha_label:
        stmt = stmt.where(m.Population.alpha_label == alpha_label)
    stmt = stmt.order_by(m.Population.imf, m.Population.z_value, m.Population.pop_type)
    return [population_summary(p) for p in db.scalars(stmt)]


@router.get("/populations/{population_id}", summary="Population detail")
def get_population(population_id: int, db: Session = Depends(get_db)) -> dict:
    population = get_population_or_404(db, population_id)
    ages = db.execute(
        select(m.Sed.age_index, m.Sed.log_age, m.Sed.log_lbol)
        .where(m.Sed.population_id == population_id)
        .order_by(m.Sed.age_index)
    ).all()
    out = population_summary(population)
    out.update(
        {
            "source_file": population.source_file,
            "sha256": population.sha256,
            "ages": [
                {"age_index": a.age_index, "log_age": a.log_age, "log_lbol": a.log_lbol}
                for a in ages
            ],
        }
    )
    return out


def _load_sed_arrays(
    db: Session, population: m.Population, age_index: int, resolution: str
) -> tuple[np.ndarray, np.ndarray, m.Sed]:
    sed = db.get(m.Sed, {"population_id": population.id, "age_index": age_index})
    if sed is None:
        raise HTTPException(404, f"no SED at age_index {age_index}")
    if resolution == "native":
        grid = db.get(m.WavelengthGrid, population.native_grid_id)
        flux = sedlib.decode_f32(sed.flux, sed.n_points)
    else:
        grid = db.get(m.WavelengthGrid, population.display_grid_id)
        flux = sedlib.decode_f32(sed.flux_ds, sed.n_points_ds)
    wavelength = sedlib.decode_f64(grid.data, grid.n_points)
    return wavelength, flux, sed


@router.get("/populations/{population_id}/sed", summary="Native-resolution SED at one age")
def get_sed(
    population_id: int,
    log_age: float | None = Query(
        None,
        ge=6.0,
        le=11.0,
        description="log10(age/yr) on the BPASS 0.1 dex grid (6.0–11.0). Prefer this over age_index.",
    ),
    age_index: int | None = Query(None, ge=0, le=50, description="0–50 grid index; prefer log_age"),
    resolution: str = Query("native", pattern="^(display|native)$"),
    mass: float = Query(1e6, gt=0, description="Formed stellar mass in Msun (BPASS native: 1e6)"),
    dust_law: str | None = None,
    ebv: float = Query(0.0, ge=0.0, le=5.0),
    rv: float | None = Query(None, ge=2.0, le=6.0, description="R_V for CCM89/F99 (2.0–6.0)"),
    redshift: float = Query(0.0, ge=0.0, le=zlib.MAX_REDSHIFT),
    igm: str = Query(
        "none",
        pattern=IGM_PARAM_PATTERN,
        description="IGM attenuation applied in the observer frame when redshift > 0",
    ),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    """SED at one age, native wavelength grid by default.

    ``log_age`` is log10(age/yr), snapped to BPASS's 0.1 dex grid (6.0 = 1 Myr … 11.0 =
    100 Gyr). ``redshift=0`` (default): rest frame, L_sun/Å. ``redshift>0``:
    observer frame — wavelengths stretched by (1+z) and flux returned as f_λ in
    erg/s/cm²/Å at the luminosity distance of z (flat ΛCDM, H0=70, Ωm=0.3).
    Pipeline order: mass → dust (rest frame, inside the law's validity window
    only) → redshift → IGM (observer frame, ``igm=inoue14|madau95``).
    ``native`` resolution is the science grid; ``display`` is a rebinned copy
    used only by the in-browser explorer.
    """
    age_index = resolve_age_index(age_index, log_age)
    population = get_population_or_404(db, population_id)
    wavelength, flux, sed = _load_sed_arrays(db, population, age_index, resolution)
    pipe = run_pipeline(
        wavelength, flux, mass=mass, dust_law=dust_law, ebv=ebv, rv=rv, z=redshift, igm=igm
    )
    wavelength, flux = pipe.wl_obs, pipe.flux_obs
    dust_info, igm_payload = pipe.dust_info, pipe.igm_info
    dl_mpc = zlib.luminosity_distance_mpc(redshift) if redshift > 0 else None

    if format == "csv":
        buf = io.StringIO()
        buf.write(f"# bib SED — population {population_id}, log(age/yr)={sed.log_age}\n")
        buf.write(f"# mass={mass} Msun; dust={dust_info}\n")
        buf.write(f"# igm: {igm_payload['label'] if igm_payload else 'none'}\n")
        buf.write("# pipeline: mass -> dust (rest frame) -> redshift -> igm (observer frame)\n")
        if redshift > 0:
            buf.write(
                f"# redshift={redshift}; D_L={dl_mpc:.2f} Mpc ({zlib.COSMOLOGY_LABEL}); "
                "observer-frame wavelengths\n"
            )
            buf.write("wavelength_angstrom_observed,flux_erg_s_cm2_angstrom\n")
        else:
            buf.write("wavelength_angstrom,flux_lsun_per_angstrom\n")
        np.savetxt(buf, np.column_stack([wavelength, flux]), delimiter=",", fmt="%.8e")
        buf.seek(0)
        name = f"bib_sed_pop{population_id}_logage{sed.log_age:.1f}_{resolution}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={name}"},
        )

    return {
        "population_id": population_id,
        "age_index": age_index,
        "redshift": redshift,
        "flux_unit": pipe.flux_unit,
        "luminosity_distance_mpc": dl_mpc,
        "log_age": sed.log_age,
        "log_lbol": sed.log_lbol,
        "resolution": resolution,
        "mass": mass,
        "dust": dust_info,
        "igm": igm_payload,
        "pipeline": ["mass", "dust (rest frame)", "redshift", "igm (observer frame)"],
        "wavelength": sig_round(wavelength, 6),
        "flux": sig_round(flux, 4),
    }


@router.get(
    "/populations/{population_id}/sed_frames",
    summary="All 51 display-resolution SEDs (for age playback)",
    include_in_schema=False,
)
def get_sed_frames(
    population_id: int,
    mass: float = Query(1e6, gt=0),
    dust_law: str | None = None,
    ebv: float = Query(0.0, ge=0.0, le=5.0),
    rv: float | None = Query(None, ge=2.0, le=6.0),
    db: Session = Depends(get_db),
) -> dict:
    """Compact rest-frame frame stack for smooth playback (display resolution only).

    Redshift and IGM are applied client-side; see ``/igm_transmission``.
    """
    population = get_population_or_404(db, population_id)
    grid = db.get(m.WavelengthGrid, population.display_grid_id)
    wavelength = sedlib.decode_f64(grid.data, grid.n_points)
    seds = db.scalars(
        select(m.Sed).where(m.Sed.population_id == population_id).order_by(m.Sed.age_index)
    ).all()
    frames = []
    dust_info = None
    for sed in seds:
        flux = sedlib.decode_f32(sed.flux_ds, sed.n_points_ds)
        pipe = run_pipeline(
            wavelength, flux, mass=mass, dust_law=dust_law, ebv=ebv, rv=rv, z=0.0, igm=None
        )
        flux, dust_info = pipe.flux_rest, pipe.dust_info
        frames.append(
            {
                "age_index": sed.age_index,
                "log_age": sed.log_age,
                "log_lbol": sed.log_lbol,
                "flux": sig_round(flux, 4),
            }
        )
    return {
        "population_id": population_id,
        "mass": mass,
        "dust": dust_info,
        "wavelength": sig_round(wavelength, 6),
        "frames": frames,
    }


@router.get(
    "/igm_transmission",
    summary="Mean IGM transmission on a population's display wavelength grid",
)
def get_igm_transmission(
    population_id: int,
    redshift: float = Query(..., gt=0.0, le=zlib.MAX_REDSHIFT),
    model: str = Query("inoue14", pattern="^(" + "|".join(sorted(IGM_MODELS)) + ")$"),
    db: Session = Depends(get_db),
) -> dict:
    """Transmission e^{-τ_eff} at λ_obs = λ_rest(1+z) for each display-grid wavelength.

    The SSP Explorer multiplies its rest-frame frames by this array after
    redshifting them, so what you see matches ``/sed?igm=…`` exactly.
    """
    population = get_population_or_404(db, population_id)
    grid = db.get(m.WavelengthGrid, population.display_grid_id)
    wavelength = sedlib.decode_f64(grid.data, grid.n_points)
    trans = igm_transmission(wavelength * (1.0 + redshift), redshift, model)
    return {
        "population_id": population_id,
        "redshift": redshift,
        "igm": igm_info(redshift, model),
        "wavelength_rest": sig_round(wavelength, 6),
        "transmission": sig_round(trans, 4),
    }


@router.get("/populations/{population_id}/timeseries", summary="Per-age product table")
def get_timeseries(
    population_id: int,
    table: str = Query(pattern="^(colours|ionizing|starmass|sn_rates|yields|mlratio|star_counts)$"),
    db: Session = Depends(get_db),
) -> dict:
    get_population_or_404(db, population_id)
    model, fields = _TIMESERIES_TABLES[table]
    rows = db.scalars(
        select(model).where(model.population_id == population_id).order_by(model.age_index)
    ).all()
    if not rows:
        raise HTTPException(404, f"no {table} data for population {population_id}")
    return {
        "population_id": population_id,
        "table": table,
        "log_age": [r.log_age for r in rows],
        "columns": {f: [getattr(r, f) for r in rows] for f in fields},
    }
