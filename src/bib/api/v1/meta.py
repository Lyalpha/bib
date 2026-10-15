"""Metadata endpoints: what's loaded, what can be selected."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bib.db import models as m
from bib.db.session import get_db
from bib.science.dust import DUST_LAWS
from bib.science.imf import describe_imf, unique_imf_payloads
from bib.science.redshift import COSMOLOGY_LABEL, MAX_REDSHIFT
from bib.science.sed import BPASS_LOG_AGES

router = APIRouter()


@router.get("/meta", summary="Available releases, grids and selection options")
def get_meta(db: Session = Depends(get_db)) -> dict:
    """Everything the UI needs to build its selectors in one call."""
    releases = []
    for release in db.scalars(select(m.Release).order_by(m.Release.version)):
        count = db.scalar(
            select(func.count()).select_from(m.Population).where(m.Population.release_id == release.id)
        )
        if not count:
            continue
        releases.append(
            {
                "id": release.id,
                "version": release.version,
                "name": release.name,
                "citation": release.citation,
                "url": release.url,
                "n_populations": count,
            }
        )

    rows = db.execute(
        select(
            m.Population.release_id,
            m.Population.imf,
            m.Population.z_label,
            m.Population.z_value,
            m.Population.pop_type,
            m.Population.alpha_label,
            m.Population.id,
        )
    ).all()

    has_synthetic = bool(
        db.scalar(select(m.Population.id).where(m.Population.is_synthetic).limit(1))
        or db.scalar(select(m.StellarModel.id).where(m.StellarModel.is_synthetic).limit(1))
    )

    return {
        "releases": releases,
        "populations": [
            {
                "id": r.id,
                "release_id": r.release_id,
                "imf": r.imf,
                "imf_info": describe_imf(r.imf).to_public_dict(),
                "z_label": r.z_label,
                "z_value": r.z_value,
                "pop_type": r.pop_type,
                "alpha_label": r.alpha_label,
            }
            for r in rows
        ],
        "log_ages": [float(a) for a in BPASS_LOG_AGES],
        "dust_laws": [
            {
                "key": law.key,
                "label": law.label,
                "note": law.note,
                "fixed_rv": law.fixed_rv,
                "default_rv": law.default_rv,
                "valid_range_a": list(law.wavelength_range_a),
            }
            for law in DUST_LAWS.values()
        ],
        "imfs": unique_imf_payloads([r.imf for r in rows]),
        "has_synthetic": has_synthetic,
        "cosmology": {
            "label": COSMOLOGY_LABEL,
            "h0": 70.0,
            "om0": 0.3,
            "max_redshift": MAX_REDSHIFT,
        },
    }
