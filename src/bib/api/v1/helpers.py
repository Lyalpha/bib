"""Shared helpers for API v1 endpoints."""

from __future__ import annotations

import numpy as np
from fastapi import HTTPException
from sqlalchemy.orm import Session

from bib.db import models as m
from bib.science.imf import describe_imf
from bib.science.sed import BPASS_LOG_AGES


def resolve_age_index(age_index: int | None, log_age: float | None) -> int:
    """Map public ``log_age`` (preferred) or the 0–50 ``age_index`` to a grid row.

    BPASS ages are log10(yr) = 6.0, 6.1, … 11.0.
    """
    if log_age is None and age_index is None:
        raise HTTPException(
            status_code=422,
            detail="provide log_age (log10(age/yr) on the 0.1 dex grid 6.0–11.0) or age_index",
        )
    if log_age is not None:
        idx = int(round((float(log_age) - 6.0) / 0.1))
        if idx < 0 or idx >= BPASS_LOG_AGES.size:
            raise HTTPException(status_code=422, detail="log_age must be between 6.0 and 11.0")
        if age_index is not None and int(age_index) != idx:
            raise HTTPException(status_code=422, detail="age_index and log_age disagree")
        return idx
    idx = int(age_index)
    if idx < 0 or idx >= BPASS_LOG_AGES.size:
        raise HTTPException(status_code=422, detail="age_index must be 0–50")
    return idx


def sig_round(values: np.ndarray, digits: int = 4) -> list[float]:
    """Round to significant digits (keeps JSON payloads compact)."""
    a = np.asarray(values, dtype=float)
    out = np.zeros_like(a)
    finite = np.isfinite(a) & (a != 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = 10.0 ** (digits - 1 - np.floor(np.log10(np.abs(a[finite]))))
    out[finite] = np.round(a[finite] * scale) / scale
    out[~np.isfinite(a)] = np.nan
    return [None if not np.isfinite(v) else float(v) for v in out]


def get_population_or_404(session: Session, population_id: int) -> m.Population:
    population = session.get(m.Population, population_id)
    if population is None:
        raise HTTPException(status_code=404, detail=f"population {population_id} not found")
    return population


def get_model_or_404(session: Session, model_id: int) -> m.StellarModel:
    model = session.get(m.StellarModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"stellar model {model_id} not found")
    return model


def population_summary(p: m.Population) -> dict:
    return {
        "id": p.id,
        "release": p.release.version,
        "imf": p.imf,
        "imf_info": describe_imf(p.imf).to_public_dict(),
        "z_label": p.z_label,
        "z_value": p.z_value,
        "pop_type": p.pop_type,
        "alpha_label": p.alpha_label,
        "alpha_value": p.alpha_value,
        "is_synthetic": p.is_synthetic,
        "products": (p.extra or {}).get("products", []),
    }
