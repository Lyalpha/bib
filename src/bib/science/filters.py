"""Bundled filter management: loading CSVs into the database and back out."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from bib.config import get_settings
from bib.db.models import Filter
from bib.db.session import session_scope
from bib.science.photometry import FilterCurve, normalize_transmission, pivot_wavelength
from bib.science.sed import decode_f64, encode_f64

# Photometry table / API listing: mission sets first, λ only within a set.
FILTER_GROUP_ORDER = (
    "JWST",
    "HST",
    "LSST",
    "Gaia",
    "2MASS",
    "SDSS",
    "Johnson-Cousins",
    "GALEX",
)


def group_sort_key(group: str, lambda_eff: float) -> tuple[int, float]:
    try:
        rank = FILTER_GROUP_ORDER.index(group)
    except ValueError:
        rank = 90 if group != "custom" else 99
    return (rank, lambda_eff)


def load_bundled_filters(filters_dir: Path | None = None) -> tuple[int, int]:
    """Load data/filters CSVs described by filters.yaml into the DB.

    Existing rows are refreshed from the on-disk CSVs (peak-normalised 0–1).
    Returns (newly added, total available in DB).
    """
    directory = filters_dir or get_settings().filters_dir
    meta_path = Path(directory) / "filters.yaml"
    if not meta_path.is_file():
        raise FileNotFoundError(f"no filter metadata at {meta_path}")
    meta: dict[str, dict] = yaml.safe_load(meta_path.read_text()) or {}

    added = 0
    with session_scope() as session:
        by_name = {row.name: row for row in session.scalars(select(Filter)).all()}
        for name, info in meta.items():
            csv_path = Path(directory) / f"{name}.csv"
            if not csv_path.is_file():
                continue
            table = np.loadtxt(csv_path, delimiter=",", skiprows=1, ndmin=2)
            wl, tr = table[:, 0], normalize_transmission(np.clip(table[:, 1], 0.0, None))
            nz = np.flatnonzero(tr > 0)
            fields = {
                "display_name": info.get("display_name", name),
                "group_name": info.get("group", "other"),
                "facility": info.get("facility"),
                "detector_type": info.get("detector_type", "photon"),
                "n_points": int(wl.size),
                "wavelength": encode_f64(wl),
                "transmission": encode_f64(tr),
                "lambda_eff": pivot_wavelength(wl, tr),
                "lambda_min": float(wl[nz[0]]),
                "lambda_max": float(wl[nz[-1]]),
                "source": info.get("svo_id"),
                "citation": info.get("source"),
            }
            if name in by_name:
                for key, value in fields.items():
                    setattr(by_name[name], key, value)
            else:
                session.add(Filter(name=name, **fields))
                added += 1
        session.flush()
        total = len(session.scalars(select(Filter.name)).all())
    return added, total


def to_curve(row: Filter) -> FilterCurve:
    return FilterCurve(
        name=row.name,
        display_name=row.display_name,
        wavelength=decode_f64(row.wavelength, row.n_points),
        transmission=decode_f64(row.transmission, row.n_points),
        detector_type=row.detector_type,
        group=row.group_name,
        source=row.citation,
        lambda_eff=row.lambda_eff,
    )


def get_curves(session: Session, names: list[str] | None = None) -> list[FilterCurve]:
    stmt = select(Filter)
    if names:
        stmt = stmt.where(Filter.name.in_(names))
    curves = [to_curve(row) for row in session.scalars(stmt)]
    curves.sort(key=lambda c: group_sort_key(c.group, c.lambda_eff))
    return curves
