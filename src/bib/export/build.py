"""Assemble an ExportTable from loaded populations."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from bib import __version__
from bib.db import models as m
from bib.export.catalog import PRODUCTS, FieldSpec, ProductSpec, physical_field_name
from bib.export.table import Column, ExportTable, formed_mass, mass_scale
from bib.science import redshift as zlib
from bib.science.filters import get_curves
from bib.science.imf import describe_imf
from bib.science.sed import BPASS_LOG_AGES


def find_populations(
    db: Session,
    *,
    release: str | None,
    imf: str | None,
    z_label: str | None,
    pop_type: str | None,
    alpha_label: str | None,
    all_z: bool,
) -> list[m.Population]:
    stmt = select(m.Population).options(joinedload(m.Population.release))
    if release:
        stmt = stmt.join(m.Release).where(m.Release.version == release)
    if imf:
        stmt = stmt.where(m.Population.imf == imf)
    if pop_type:
        stmt = stmt.where(m.Population.pop_type == pop_type)
    if alpha_label:
        stmt = stmt.where(m.Population.alpha_label == alpha_label)
    else:
        stmt = stmt.where(m.Population.alpha_label.is_(None))
    if z_label and not all_z:
        stmt = stmt.where(m.Population.z_label == z_label)
    stmt = stmt.order_by(m.Population.z_value, m.Population.pop_type, m.Population.imf)
    rows = list(db.scalars(stmt).unique())
    if not rows:
        raise HTTPException(404, "no loaded population matches that selection")
    if not all_z and len(rows) > 1:
        raise HTTPException(
            422,
            "several populations match; set release, IMF, metallicity, binary/single"
            " (and [α/Fe] if this is a v2.3 grid)",
        )
    if all_z:
        keys = {(p.imf, p.pop_type, p.alpha_label, p.release.version) for p in rows}
        if len(keys) > 1:
            raise HTTPException(
                422,
                "all metallicities needs a single IMF, population type and release",
            )
    return rows


def _age_indices(log_age: float | None, all_ages: bool) -> list[int]:
    from bib.api.v1.helpers import resolve_age_index

    if all_ages:
        return list(range(BPASS_LOG_AGES.size))
    if log_age is None:
        raise HTTPException(422, "set log_age or all_ages")
    return [resolve_age_index(None, log_age)]


def _pop_label(p: m.Population) -> str:
    bits = [p.release.version, p.imf, p.pop_type, p.z_label]
    if p.alpha_label:
        bits.append(p.alpha_label)
    return " · ".join(bits)


def _query_comments(
    spec: ProductSpec,
    pops: list[m.Population],
    *,
    units: str,
    mass: float,
    log_age: float | None,
    all_ages: bool,
    all_z: bool,
    dust_law: str | None,
    ebv: float,
    rv: float | None,
    redshift: float,
    filters: str | None,
) -> tuple[list[str], dict[str, Any]]:
    pop = pops[0]
    imf = describe_imf(pop.imf)
    mass_used = formed_mass(units, mass)
    age_note = (
        "all 51 BPASS ages (log10(age/yr) = 6.0 … 11.0, 0.1 dex)"
        if all_ages
        else f"log10(age/yr) = {float(log_age):.1f}  ({10 ** float(log_age):.3g} yr)"
    )
    z_note = (
        f"all loaded metallicities ({len(pops)}): "
        + ", ".join(p.z_label for p in pops)
        if all_z
        else f"{pop.z_label} (Z = {pop.z_value})"
    )
    dust_note = "none"
    if dust_law and ebv > 0:
        dust_note = f"{dust_law}, E(B-V) = {ebv:g}"
        if rv is not None:
            dust_note += f", R_V = {rv:g}"
    comments = [
        f"bib {__version__}",
        f"product: {spec.label} ({spec.key})",
        f"release: {pop.release.version}"
        + (f" — {pop.release.citation}" if pop.release.citation else ""),
        f"IMF: {imf.label} ({pop.imf})",
        f"population type: {'binary' if pop.pop_type == 'bin' else 'single-star'}",
        f"metallicity: {z_note}",
        f"age: {age_note}",
        f"units: {'as published by BPASS (10^6 Msun formed)' if units == 'native' else 'physical, scaled to formed mass'}",
        f"formed mass: {_fmt_mass(mass_used)} Msun"
        + (" (BPASS native normalisation)" if units == "native" else ""),
        f"extinction: {dust_note} (foreground screen on the SED, rest frame; light removed is not reprocessed; SED and photometry only)",
        f"redshift: {redshift:g}"
        + (
            f"; D_L = {zlib.luminosity_distance_mpc(redshift):.4g} Mpc ({zlib.COSMOLOGY_LABEL})"
            if redshift > 0
            else " (rest frame / 10 pc absolute for photometry)"
        ),
    ]
    if filters:
        comments.append(f"filters: {filters}")
    comments.append(
        "BPASS data: CC BY-NC 4.0. Cite Eldridge, Stanway et al. (2017) and "
        "Stanway & Eldridge (2018); include the BPASS acknowledgement."
    )
    if any(p.is_synthetic for p in pops):
        comments.append("WARNING: one or more matching populations are synthetic demo data, not BPASS.")
    meta = {
        "bib_version": __version__,
        "product": spec.key,
        "units": units,
        "formed_mass_msun": mass_used,
        "release": pop.release.version,
        "imf": pop.imf,
        "imf_label": imf.label,
        "pop_type": pop.pop_type,
        "metallicities": [p.z_label for p in pops],
        "log_age": None if all_ages else float(log_age),
        "all_ages": all_ages,
        "dust_law": dust_law or None,
        "ebv": ebv if dust_law and ebv > 0 else 0.0,
        "rv": rv,
        "redshift": redshift,
        "cosmology": zlib.COSMOLOGY_LABEL if redshift > 0 else None,
        "luminosity_distance_mpc": zlib.luminosity_distance_mpc(redshift) if redshift > 0 else None,
        "synthetic": any(p.is_synthetic for p in pops),
    }
    return comments, meta


def _fmt_mass(mass: float) -> str:
    if abs(mass - 1.0e6) < 1e-3:
        return "1e6"
    return f"{mass:g}"


def _filename(
    spec: ProductSpec,
    pops: list[m.Population],
    *,
    units: str,
    log_age: float | None,
    all_ages: bool,
    fmt: str,
) -> str:
    from bib.export.catalog import EXPORT_FORMATS

    ext = next(row["ext"] for row in EXPORT_FORMATS if row["key"] == fmt)
    zbit = "allz" if len(pops) > 1 else pops[0].z_label
    agebit = "allages" if all_ages else f"logage{float(log_age):.1f}"
    return f"bib_{spec.key}_{pops[0].imf}_{pops[0].pop_type}_{zbit}_{agebit}_{units}.{ext}"


def _convert_field(field: FieldSpec, values: np.ndarray, units: str, scale: float, bin_width: np.ndarray | None) -> np.ndarray:
    raw = np.asarray(values, dtype=float)
    if units == "native" or field.kind in {"intensive", "colour"}:
        return raw
    if field.kind == "log":
        out = np.full_like(raw, np.nan)
        ok = np.isfinite(raw)
        out[ok] = (10.0 ** raw[ok]) * scale
        return out
    if field.kind == "magnitude":
        if scale <= 0:
            return raw
        return raw - 2.5 * math.log10(scale)
    if field.name.startswith("n_") and bin_width is not None:
        width = np.asarray(bin_width, dtype=float)
        out = np.full_like(raw, np.nan)
        ok = np.isfinite(raw) & np.isfinite(width) & (width > 0)
        out[ok] = raw[ok] * scale / width[ok]
        return out
    return raw * scale


def _timeseries_rows(
    db: Session,
    population: m.Population,
    table_key: str,
    age_indices: list[int],
) -> list[Any]:
    from bib.api.v1.populations import _TIMESERIES_TABLES

    model, _fields = _TIMESERIES_TABLES[table_key]
    rows = db.scalars(
        select(model)
        .where(model.population_id == population.id)
        .order_by(model.age_index)
    ).all()
    if not rows:
        return []
    wanted = set(age_indices)
    return [r for r in rows if r.age_index in wanted]


def _identity_columns(pops: list[m.Population], ages: list[tuple[m.Population, int, float]]) -> list[Column]:
    cols = []
    if len(pops) > 1:
        cols.append(
            Column(
                "z_label",
                "",
                "BPASS metallicity filename tag",
                np.array([p.z_label for p, _i, _a in ages], dtype=object),
                "string",
            )
        )
        cols.append(
            Column(
                "z_value",
                "mass fraction",
                "Initial metal mass fraction Z",
                np.array([p.z_value for p, _i, _a in ages], dtype=float),
            )
        )
    cols.append(
        Column(
            "log_age",
            "dex (yr)",
            "log10(age / yr) on the BPASS 0.1 dex grid",
            np.array([a for _p, _i, a in ages], dtype=float),
        )
    )
    cols.append(
        Column(
            "age_yr",
            "yr",
            "Age in years, 10^log_age",
            np.array([10.0 ** a for _p, _i, a in ages], dtype=float),
        )
    )
    return cols


def _build_timeseries(
    db: Session,
    spec: ProductSpec,
    pops: list[m.Population],
    age_indices: list[int],
    units: str,
    mass: float,
    prefix: str = "",
) -> list[Column]:
    scale = mass_scale(units, mass)
    ages: list[tuple[m.Population, int, float]] = []
    store: dict[str, list] = {f.name: [] for f in spec.fields}
    widths: list[float] = []
    for pop in pops:
        rows = _timeseries_rows(db, pop, spec.table, age_indices)
        if not rows:
            continue
        for row in rows:
            ages.append((pop, row.age_index, float(row.log_age)))
            for field in spec.fields:
                attr = field.source or field.name
                store[field.name].append(getattr(row, attr, None))
            widths.append(float(getattr(row, "bin_width_yr", float("nan"))))
    if not ages:
        raise HTTPException(404, f"no {spec.label.lower()} table for that selection")
    bin_width = np.array(widths, dtype=float) if spec.key == "sn_rates" else None
    cols = [] if prefix else _identity_columns(pops, ages)
    for field in spec.fields:
        if field.name == "bin_width_yr" and units == "physical" and spec.key == "sn_rates":
            continue
        values = _convert_field(field, store[field.name], units, scale, bin_width)
        name = prefix + (physical_field_name(field, spec.key) if units == "physical" else field.name)
        unit = field.unit_physical if units == "physical" else field.unit_native
        desc = field.description
        if units == "physical" and field.kind == "log":
            desc = f"{desc} (linear)"
        if units == "physical" and spec.key == "sn_rates" and field.name.startswith("n_"):
            desc = f"{desc} (rate = count × formed-mass scale / bin width)"
        cols.append(Column(name, unit, desc, values))
    return cols


def _build_sed(
    db: Session,
    pops: list[m.Population],
    age_indices: list[int],
    units: str,
    mass: float,
    dust_law: str | None,
    ebv: float,
    rv: float | None,
    redshift: float,
) -> list[Column]:
    from bib.api.v1.populations import _apply_transforms, _load_sed_arrays

    pop = pops[0]
    mass_used = formed_mass(units, mass)
    wavelength = None
    flux_by_age: list[tuple[float, np.ndarray]] = []
    dust_info = None
    for idx in age_indices:
        wl, flux, sed = _load_sed_arrays(db, pop, idx, "native")
        flux, dust_info = _apply_transforms(wl, flux, mass_used, dust_law, ebv, rv)
        if redshift > 0:
            wl, flux = zlib.observe(wl, flux, redshift)
        if wavelength is None:
            wavelength = wl
        flux_by_age.append((float(sed.log_age), flux))
    assert wavelength is not None
    if redshift > 0:
        flux_unit = "erg s^-1 cm^-2 Å^-1"
        flux_desc = (
            f"Observer-frame f_λ at D_L for z = {redshift:g} "
            f"({zlib.COSMOLOGY_LABEL}); extinction applied in the rest frame"
        )
        wl_desc = "Observer-frame wavelength (λ_rest × (1+z))"
        wl_name = "wavelength_angstrom_observed"
    else:
        flux_unit = "Lsun Å^-1"
        flux_desc = f"Rest-frame L_λ for {_fmt_mass(mass_used)} Msun formed"
        wl_desc = "Rest-frame wavelength"
        wl_name = "wavelength_angstrom"
    cols = [Column(wl_name, "Å", wl_desc, wavelength)]
    if len(flux_by_age) == 1:
        cols.append(Column("flux", flux_unit, flux_desc, flux_by_age[0][1]))
    else:
        for log_age, flux in flux_by_age:
            cols.append(
                Column(
                    f"flux_logage{log_age:.1f}",
                    flux_unit,
                    f"{flux_desc}; log10(age/yr) = {log_age:.1f}",
                    flux,
                )
            )
    if dust_info:
        cols[0].description += f"; dust {dust_info['law']} E(B-V)={dust_info['ebv']:g}"
    return cols


def _build_photometry(
    db: Session,
    pops: list[m.Population],
    age_indices: list[int],
    units: str,
    mass: float,
    dust_law: str | None,
    ebv: float,
    rv: float | None,
    redshift: float,
    filters: str | None,
) -> list[Column]:
    from bib.api.v1.photometry import _native_sed, _observe, _photometry_payload, _transform

    pop = pops[0]
    mass_used = formed_mass(units, mass)
    names = [n.strip() for n in filters.split(",") if n.strip()] if filters else None
    curves = get_curves(db, names)
    if names and len(curves) != len(names):
        missing = set(names) - {c.name for c in curves}
        raise HTTPException(404, f"unknown filters: {sorted(missing)}")
    rows: list[dict] = []
    for idx in age_indices:
        wavelength, flux, sed = _native_sed(db, pop.id, idx)
        flux, _dust = _transform(wavelength, flux, mass_used, dust_law, ebv, rv)
        wl_obs, flam = _observe(wavelength, flux, redshift)
        for entry in _photometry_payload(wl_obs, flam, curves, redshift):
            rows.append({**entry, "log_age": float(sed.log_age)})
    def col(name, unit, desc, key, datatype="float64"):
        values = [r.get(key) for r in rows]
        if datatype == "string":
            return Column(name, unit, desc, np.array(values, dtype=object), "string")
        arr = np.array([np.nan if v is None else float(v) for v in values], dtype=float)
        return Column(name, unit, desc, arr)

    out = []
    if len(age_indices) > 1:
        out.append(col("log_age", "dex (yr)", "log10(age / yr)", "log_age"))
        out.append(
            Column(
                "age_yr",
                "yr",
                "Age in years",
                np.array([10.0 ** r["log_age"] for r in rows], dtype=float),
            )
        )
    out.extend(
        [
            col("filter", "", "Bundled filter id", "filter", "string"),
            col("display_name", "", "Filter display name", "display_name", "string"),
            col("group", "", "Instrument / survey group", "group", "string"),
            col("lambda_eff", "Å", "Effective wavelength", "lambda_eff"),
            col(
                "ab_mag",
                "mag (AB)",
                "Apparent AB if z>0, otherwise absolute AB at 10 pc",
                "ab_mag",
            ),
            col("coverage", "fraction", "Filter transmission overlapping the SED", "coverage"),
        ]
    )
    return out


def build_export(
    db: Session,
    *,
    product: str,
    release: str | None,
    imf: str | None,
    z_label: str | None,
    pop_type: str | None,
    alpha_label: str | None,
    all_z: bool,
    log_age: float | None,
    all_ages: bool,
    units: str,
    mass: float,
    dust_law: str | None,
    ebv: float,
    rv: float | None,
    redshift: float,
    filters: str | None,
    fmt: str,
) -> ExportTable:
    spec = PRODUCTS.get(product)
    if spec is None:
        raise HTTPException(422, f"unknown product '{product}'")
    if all_z and not spec.allows_all_z:
        raise HTTPException(422, f"{spec.label} is one population at a time")
    if units not in {"native", "physical"}:
        raise HTTPException(422, "units must be native or physical")
    pops = find_populations(
        db,
        release=release,
        imf=imf,
        z_label=z_label,
        pop_type=pop_type,
        alpha_label=alpha_label,
        all_z=all_z,
    )
    age_indices = _age_indices(log_age, all_ages)
    comments, meta = _query_comments(
        spec,
        pops,
        units=units,
        mass=mass,
        log_age=log_age,
        all_ages=all_ages,
        all_z=all_z,
        dust_law=dust_law,
        ebv=ebv,
        rv=rv,
        redshift=redshift,
        filters=filters,
    )
    if spec.key == "sed":
        columns = _build_sed(
            db, pops, age_indices, units, mass, dust_law, ebv, rv, redshift
        )
    elif spec.key == "photometry":
        columns = _build_photometry(
            db, pops, age_indices, units, mass, dust_law, ebv, rv, redshift, filters
        )
    elif spec.bundle:
        columns = _identity_columns(
            pops,
            [(pops[0], idx, float(BPASS_LOG_AGES[idx])) for idx in age_indices],
        )
        missing = []
        for key, child in PRODUCTS.items():
            if not child.table:
                continue
            try:
                extra = _build_timeseries(
                    db, child, pops, age_indices, units, mass, prefix=f"{key}__"
                )
            except HTTPException:
                missing.append(key)
                continue
            columns.extend(extra)
        if missing:
            comments.append("missing products (not loaded for this population): " + ", ".join(missing))
            meta["missing_products"] = missing
    else:
        columns = _build_timeseries(db, spec, pops, age_indices, units, mass)

    title = f"bib {spec.label}"
    return ExportTable(
        title=title,
        filename=_filename(
            spec, pops, units=units, log_age=log_age, all_ages=all_ages, fmt=fmt
        ),
        comments=comments,
        columns=columns,
        meta=meta,
    )
