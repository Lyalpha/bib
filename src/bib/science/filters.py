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
from bib.science.photometry import FilterCurve, pivot_wavelength
from bib.science.sed import decode_f64, encode_f64


def load_bundled_filters(filters_dir: Path | None = None) -> tuple[int, int]:
    """Load data/filters CSVs described by filters.yaml into the DB.

    Idempotent: existing filter names are left untouched.
    Returns (newly added, total available in DB).
    """
    directory = filters_dir or get_settings().filters_dir
    meta_path = Path(directory) / "filters.yaml"
    if not meta_path.is_file():
        raise FileNotFoundError(f"no filter metadata at {meta_path}")
    meta: dict[str, dict] = yaml.safe_load(meta_path.read_text()) or {}

    added = 0
    with session_scope() as session:
        existing = set(session.scalars(select(Filter.name)).all())
        for name, info in meta.items():
            if name in existing:
                continue
            csv_path = Path(directory) / f"{name}.csv"
            if not csv_path.is_file():
                continue
            table = np.loadtxt(csv_path, delimiter=",", skiprows=1, ndmin=2)
            wl, tr = table[:, 0], np.clip(table[:, 1], 0.0, None)
            nz = np.flatnonzero(tr > 0)
            session.add(
                Filter(
                    name=name,
                    display_name=info.get("display_name", name),
                    group_name=info.get("group", "other"),
                    facility=info.get("facility"),
                    detector_type=info.get("detector_type", "photon"),
                    n_points=int(wl.size),
                    wavelength=encode_f64(wl),
                    transmission=encode_f64(tr),
                    lambda_eff=pivot_wavelength(wl, tr),
                    lambda_min=float(wl[nz[0]]),
                    lambda_max=float(wl[nz[-1]]),
                    source=info.get("svo_id"),
                    citation=info.get("source"),
                )
            )
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
    stmt = select(Filter).order_by(Filter.lambda_eff)
    if names:
        stmt = stmt.where(Filter.name.in_(names))
    return [to_curve(row) for row in session.scalars(stmt)]
