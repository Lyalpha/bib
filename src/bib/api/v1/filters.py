"""Filter endpoints: bundled filter metadata and curves."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bib.api.v1.helpers import sig_round
from bib.db import models as m
from bib.db.session import get_db
from bib.science.sed import decode_f64

router = APIRouter()


@router.get("/filters", summary="List bundled filters")
def list_filters(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(m.Filter).order_by(m.Filter.lambda_eff)).all()
    return [
        {
            "name": f.name,
            "display_name": f.display_name,
            "group": f.group_name,
            "facility": f.facility,
            "detector_type": f.detector_type,
            "lambda_eff": f.lambda_eff,
            "lambda_min": f.lambda_min,
            "lambda_max": f.lambda_max,
            "source": f.source,
            "citation": f.citation,
        }
        for f in rows
    ]


@router.get("/filters/{name}/curve", summary="Filter transmission curve")
def get_filter_curve(name: str, db: Session = Depends(get_db)) -> dict:
    row = db.scalar(select(m.Filter).where(m.Filter.name == name))
    if row is None:
        raise HTTPException(404, f"filter '{name}' not found")
    return {
        "name": row.name,
        "display_name": row.display_name,
        "detector_type": row.detector_type,
        "lambda_eff": row.lambda_eff,
        "wavelength": sig_round(decode_f64(row.wavelength, row.n_points), 6),
        "transmission": sig_round(decode_f64(row.transmission, row.n_points), 4),
    }
