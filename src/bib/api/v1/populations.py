"""Population endpoints: listing, SEDs, per-age products, HRD grids."""

from __future__ import annotations

import io

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from bib.api.v1.helpers import (
    encode_u8_log,
    get_population_or_404,
    population_summary,
    resolve_age_index,
    sig_round,
)
from bib.db import models as m
from bib.db.session import get_db
from bib.science import redshift as zlib
from bib.science import sed as sedlib
from bib.science.dust import DUST_LAWS, apply_dust

router = APIRouter()

_TIMESERIES_TABLES: dict[str, tuple[type, list[str]]] = {
    "colours": (m.Colours, [
        "v_minus_i", "mag_u", "mag_b", "mag_v", "mag_r", "mag_i", "mag_j", "mag_h", "mag_k",
        "sdss_u", "sdss_g", "sdss_r", "sdss_i", "sdss_z",
        "f300w", "f336w", "f435w", "f450w", "f555w", "f606w", "f814w",
    ]),
    "ionizing": (m.Ionizing, ["log_nion", "log_l_halpha", "log_l_fuv", "log_l_nuv"]),
    "starmass": (m.StarMass, ["mass_stars", "mass_remnants"]),
    "sn_rates": (m.SnRates, [
        "n_ia", "n_iip", "n_ii_other", "n_ib", "n_ic", "n_grb", "n_pisn", "n_low_mass",
        "bin_width_yr",
    ]),
    "yields": (m.Yields, [
        "wind_h", "wind_he", "wind_z", "wind_energy", "sn_energy", "sn_h", "sn_he", "sn_z",
    ]),
    "mlratio": (m.MLRatio, ["ml_k", "ml_v"]),
    "star_counts": (m.StarCounts, [
        "n_o_hi", "n_of_hi", "n_b_hi", "n_a_hi", "n_ysg_hi",
        "n_k_hi", "n_m_hi", "n_wnh_hi", "n_wn_hi", "n_wc_hi",
        "n_o_lo", "n_of_lo", "n_b_lo", "n_a_lo", "n_ysg_lo",
        "n_k_lo", "n_m_lo", "n_wnh_lo", "n_wn_lo", "n_wc_lo",
    ]),
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


def _apply_transforms(
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
        flux = result.flux
        dust_info = {
            "law": dust_law,
            "ebv": ebv,
            "rv": result.rv,
            "a_v": result.a_v,
            "applied_range_a": list(result.applied_range_a),
        }
    return flux, dust_info


@router.get("/populations/{population_id}/sed", summary="Native-resolution SED at one age")
def get_sed(
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
    resolution: str = Query("native", pattern="^(display|native)$"),
    mass: float = Query(1e6, gt=0, description="Formed stellar mass in Msun (BPASS native: 1e6)"),
    dust_law: str | None = None,
    ebv: float = Query(0.0, ge=0.0, le=5.0),
    rv: float | None = Query(None, gt=1.0, lt=10.0),
    redshift: float = Query(0.0, ge=0.0, le=zlib.MAX_REDSHIFT),
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    """SED at one age, native wavelength grid by default.

    ``log_age`` is log10(age/yr), snapped to BPASS's 0.1 dex grid (6.0 = 1 Myr … 11.0 =
    100 Gyr). ``redshift=0`` (default): rest frame, L_sun/Å. ``redshift>0``:
    observer frame — wavelengths stretched by (1+z) and flux returned as f_λ in
    erg/s/cm²/Å at the luminosity distance of z (flat ΛCDM, H0=70, Ωm=0.3);
    dust is applied in the rest frame first. ``native`` resolution is the
    science grid; ``display`` is a rebinned copy used only by the in-browser
    explorer.
    """
    age_index = resolve_age_index(age_index, log_age)
    population = get_population_or_404(db, population_id)
    wavelength, flux, sed = _load_sed_arrays(db, population, age_index, resolution)
    flux, dust_info = _apply_transforms(wavelength, flux, mass, dust_law, ebv, rv)

    flux_unit = "lsun_per_angstrom (rest frame)"
    dl_mpc = None
    if redshift > 0:
        wavelength, flux = zlib.observe(wavelength, flux, redshift)
        flux_unit = "erg/s/cm2/angstrom (observer frame at D_L)"
        dl_mpc = zlib.luminosity_distance_mpc(redshift)

    if format == "csv":
        buf = io.StringIO()
        buf.write(f"# bib SED — population {population_id}, log(age/yr)={sed.log_age}\n")
        buf.write(f"# mass={mass} Msun; dust={dust_info}\n")
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
        "flux_unit": flux_unit,
        "luminosity_distance_mpc": dl_mpc,
        "log_age": sed.log_age,
        "log_lbol": sed.log_lbol,
        "resolution": resolution,
        "mass": mass,
        "dust": dust_info,
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
    rv: float | None = Query(None, gt=1.0, lt=10.0),
    db: Session = Depends(get_db),
) -> dict:
    """Compact frame stack for smooth playback (display resolution only)."""
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
        flux, dust_info = _apply_transforms(wavelength, flux, mass, dust_law, ebv, rv)
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
        "columns": {
            f: [getattr(r, f) for r in rows] for f in fields
        },
    }


@router.get("/populations/{population_id}/hrd", summary="HRD occupation grids (all ages)")
def get_hrd(
    population_id: int,
    diagram: str = Query("TL", pattern="^(TL|TG|TTG)$"),
    split_classes: bool = Query(False, description="Return the three surface-H classes separately"),
    db: Session = Depends(get_db),
) -> dict:
    """Log-quantized uint8 grids (base64), one frame per age — built for playback.

    Grid values are stellar occupation densities; decode with
    ``value = 10^(lo + q/255 * (hi - lo))`` for q > 0, empty cells are q = 0.
    """
    get_population_or_404(db, population_id)
    rows = db.scalars(
        select(m.HrdGrid)
        .where(m.HrdGrid.population_id == population_id, m.HrdGrid.diagram == diagram)
        .order_by(m.HrdGrid.age_index, m.HrdGrid.h_class)
    ).all()
    if not rows:
        raise HTTPException(404, f"no {diagram} HRD grids for population {population_id}")

    by_age: dict[int, dict] = {}
    grids_by_age: dict[int, list[np.ndarray]] = {}
    for row in rows:
        grid = sedlib.decode_f32(row.grid, 100 * 100).reshape(100, 100)
        by_age.setdefault(row.age_index, {"log_age": row.log_age})
        grids_by_age.setdefault(row.age_index, []).append(grid)

    global_max = max(float(np.max(np.sum(g, axis=0))) for g in
                     (np.stack(v) for v in grids_by_age.values()))
    floor_ratio = 1e-4

    frames = []
    for age_index in sorted(grids_by_age):
        stack = grids_by_age[age_index]
        if split_classes:
            payload = {"classes": [encode_u8_log(g, global_max, floor_ratio) for g in stack]}
        else:
            payload = {"grid": encode_u8_log(np.sum(stack, axis=0), global_max, floor_ratio)}
        frames.append({"age_index": age_index, "log_age": by_age[age_index]["log_age"], **payload})

    return {
        "population_id": population_id,
        "diagram": diagram,
        "nx": 100,
        "ny": 100,
        "axes": {
            "log_t": {"min": 0.1, "max": 10.0, "step": 0.1, "note": "rows"},
            "col": {"min": -2.9, "max": 7.0, "step": 0.1, "note": "columns; logL, logg or log(T^4/g)"},
        },
        "scale": {
            "mode": "log-uint8",
            "global_max": global_max,
            "floor_ratio": floor_ratio,
            "lo": float(np.log10(global_max * floor_ratio)) if global_max > 0 else 0.0,
            "hi": float(np.log10(global_max)) if global_max > 0 else 0.0,
        },
        "split_classes": split_classes,
        "frames": frames,
    }
