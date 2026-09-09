"""Stellar model endpoints: search and track payloads for the HR explorer."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from bib.api.v1.helpers import get_model_or_404, sig_round
from bib.db import models as m
from bib.db.session import get_db
from bib.science.tracks import decimate_indices, mass_loss_rate, roche_radii_rsun

router = APIRouter()

_LOG_T_SUN = 3.7617


def _model_summary(model: m.StellarModel) -> dict:
    return {
        "id": model.id,
        "z_label": model.z_label,
        "z_value": model.z_value,
        "kind": model.kind,
        "filename": model.filename,
        "m1_init": model.m1_init,
        "q_init": model.q_init,
        "logp_init": model.logp_init,
        "mrem_init": model.mrem_init,
        "n_steps": model.n_steps,
        "final_mass": model.final_mass,
        "curated": model.curated,
        "title": model.title,
        "description": model.description,
        "is_synthetic": model.is_synthetic,
    }


@router.get("/models", summary="Search stellar models")
def list_models(
    kind: str | None = Query(None, pattern="^(single|primary|secondary)$"),
    z_label: str | None = None,
    m1_min: float | None = None,
    m1_max: float | None = None,
    curated: bool | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(m.StellarModel)
    if kind:
        stmt = stmt.where(m.StellarModel.kind == kind)
    if z_label:
        stmt = stmt.where(m.StellarModel.z_label == z_label)
    if m1_min is not None:
        stmt = stmt.where(m.StellarModel.m1_init >= m1_min)
    if m1_max is not None:
        stmt = stmt.where(m.StellarModel.m1_init <= m1_max)
    if curated is not None:
        stmt = stmt.where(m.StellarModel.curated == curated)
    stmt = stmt.order_by(
        m.StellarModel.z_value.desc(), m.StellarModel.kind, m.StellarModel.m1_init
    ).limit(limit)
    return [_model_summary(model) for model in db.scalars(stmt)]


@router.get("/models/{model_id}", summary="Stellar model detail")
def get_model(model_id: int, db: Session = Depends(get_db)) -> dict:
    model = get_model_or_404(db, model_id)
    out = _model_summary(model)
    out["source_file"] = model.source_file
    out["sha256"] = model.sha256
    out["events"] = [
        {
            "event_type": e.event_type,
            "step": e.step,
            "age_yr": e.age_yr,
            "label": e.label,
            "note": e.note,
        }
        for e in model.events
    ]
    return out


def _column(steps: list[m.StellarModelStep], name: str) -> np.ndarray:
    return np.asarray(
        [getattr(s, name) if getattr(s, name) is not None else np.nan for s in steps],
        dtype=float,
    )


@router.get("/models/{model_id}/track", summary="Full track payload for animation")
def get_track(
    model_id: int,
    max_points: int = Query(1500, ge=100, le=20000),
    db: Session = Depends(get_db),
) -> dict:
    """Track arrays + derived binary geometry, decimated but event-preserving.

    Included derived quantities:
      - ``mdot1``: |dM1/dt| in Msun/yr from finite differences of mass vs age
        (the raw sneplot rate columns have ambiguous units and are only used
        as flags — ``rlof_active`` comes from DM1R > 0).
      - ``rl1_rsun``/``rl2_rsun``: Eggleton (1983) Roche-lobe radii.
      - ``r1_rsun``/``r2_rsun``: stellar radii (companion from log R2 when
        present, else from L and Teff estimates).
    """
    model = get_model_or_404(db, model_id)
    steps = db.scalars(
        select(m.StellarModelStep)
        .where(m.StellarModelStep.model_id == model_id)
        .order_by(m.StellarModelStep.step)
    ).all()

    age = _column(steps, "age_yr")
    m1 = _column(steps, "m1")
    m2 = _column(steps, "m2")
    log_sep = _column(steps, "log_sep")
    sep_rsun = 10.0**log_sep
    rl1, rl2 = roche_radii_rsun(m1, m2, sep_rsun)

    log_r2 = _column(steps, "log_r2")
    log_t2 = _column(steps, "log_t2")
    log_l2 = _column(steps, "log_l2")
    r2_est = 10.0 ** (0.5 * log_l2 - 2.0 * (log_t2 - _LOG_T_SUN))
    r2 = np.where(np.isfinite(log_r2), 10.0**log_r2, r2_est)

    dm1r = _column(steps, "dm1r")
    rlof_active = np.nan_to_num(dm1r, nan=0.0) > 0

    # event steps -> indices into the step arrays
    step_numbers = np.asarray([s.step for s in steps])
    event_indices: set[int] = set()
    events_payload = []
    for event in model.events:
        idx = int(np.searchsorted(step_numbers, event.step))
        idx = min(idx, len(steps) - 1)
        event_indices.add(idx)
        events_payload.append(
            {
                "event_type": event.event_type,
                "step": event.step,
                "index": idx,
                "age_yr": event.age_yr,
                "label": event.label,
                "note": event.note,
            }
        )

    keep = decimate_indices(len(steps), max_points, event_indices)
    # remap event indices to the decimated arrays
    remap = {int(orig): int(new) for new, orig in enumerate(keep)}
    for entry in events_payload:
        entry["index"] = remap.get(entry["index"], int(np.searchsorted(keep, entry["index"])))

    def col(values: np.ndarray, digits: int = 5) -> list:
        return sig_round(values[keep], digits)

    arrays = {
        "age_yr": col(age, 6),
        "log_t1": col(_column(steps, "log_t1")),
        "log_l1": col(_column(steps, "log_l1")),
        "log_r1": col(_column(steps, "log_r1")),
        "m1": col(m1),
        "he_core": col(_column(steps, "he_core")),
        "co_core": col(_column(steps, "co_core")),
        "one_core": col(_column(steps, "one_core")),
        "x_surf": col(_column(steps, "x_surf")),
        "y_surf": col(_column(steps, "y_surf")),
        "c_surf": col(_column(steps, "c_surf")),
        "n_surf": col(_column(steps, "n_surf")),
        "o_surf": col(_column(steps, "o_surf")),
        "ne_surf": col(_column(steps, "ne_surf")),
        "mdot1": col(mass_loss_rate(age, m1), 4),
        "m2": col(m2),
        "sep_rsun": col(sep_rsun),
        "period_yr": col(_column(steps, "period_yr")),
        "rl1_rsun": col(rl1),
        "rl2_rsun": col(rl2),
        "r1_rsun": col(10.0 ** _column(steps, "log_r1")),
        "r2_rsun": col(r2),
        "log_t2": col(log_t2),
        "log_l2": col(log_l2),
        "rlof_active": [bool(v) for v in rlof_active[keep]],
    }

    return {
        "model": _model_summary(model),
        "n_points": int(keep.size),
        "n_points_full": len(steps),
        "arrays": arrays,
        "events": sorted(events_payload, key=lambda e: e["age_yr"]),
        "notes": [
            "mdot1 is derived from finite differences of mass vs age; raw sneplot "
            "mass-transfer columns are used only as activity flags.",
            "Companion radius/temperature are BPASS estimates and may be absent.",
        ],
    }
