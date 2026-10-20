"""The single SED transformation pipeline shared by every API route.

Order of operations (fixed, and stated in every payload):

1. **mass** — scale the BPASS 10⁶ M☉ SED to the requested formed mass;
2. **dust** — foreground-screen extinction in the *rest* frame, applied only
   inside the chosen law's validity window (no extrapolation);
3. **redshift** — stretch wavelengths by (1+z) and convert L_λ to observed
   f_λ at the luminosity distance;
4. **IGM** — multiply the *observer-frame* spectrum by the mean Lyman-series
   plus Lyman-continuum transmission of the chosen prescription (only when
   z > 0 and a model is requested).

:func:`run_pipeline` returns the arrays plus the serialisable ``dust`` /
``igm`` descriptors, and :func:`filter_status` derives the per-filter
"what was actually applied inside this passband" flags that accompany every
photometric magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from fastapi import HTTPException

from bib.science import redshift as zlib
from bib.science import sed as sedlib
from bib.science.dust import DUST_LAWS, DustLaw, DustResult, apply_dust
from bib.science.igm import IGM_MODELS, LYMAN_ALPHA_A, igm_info, igm_transmission
from bib.science.photometry import FilterCurve

IGM_PARAM_PATTERN = "^(none|" + "|".join(sorted(IGM_MODELS)) + ")$"

# Controlled vocabulary for the per-filter flags -----------------------------
DUST_STATUS_NONE = "none"  # no extinction requested
DUST_STATUS_APPLIED = "applied"  # whole passband inside the law's window
DUST_STATUS_PARTIAL = "partial"  # passband straddles the window edge
DUST_STATUS_NOT_APPLIED = "not_applied"  # requested, but passband entirely outside the window

IGM_STATUS_NONE = "none"  # IGM has no bearing (z = 0 or passband redward of Lyα(1+z))
IGM_STATUS_APPLIED = "applied"  # model requested and passband reaches into the IGM-affected range
IGM_STATUS_NOT_APPLIED = "not_applied"  # no model requested, but the passband is IGM-affected

LABEL_DUST = "dust-extinguished"
LABEL_IGM = "IGM-attenuated"
LABEL_BOTH = "dust-extinguished, IGM-attenuated"
LABEL_NEITHER = "unattenuated"


@dataclass
class PipelineResult:
    wl_rest: np.ndarray
    flux_rest: np.ndarray  # L_sun/Å after mass + dust (rest frame)
    wl_obs: np.ndarray  # == wl_rest at z = 0
    flux_obs: np.ndarray  # f_λ erg/s/cm²/Å at D_L when z > 0; else == flux_rest
    redshift: float
    mass: float
    dust: DustResult | None
    ebv: float  # requested E(B-V) (0 when no dust was applied)
    igm_model: str | None  # None when nothing was applied
    igm_factor: np.ndarray | None  # transmission on wl_obs, or None

    @property
    def dust_law(self) -> DustLaw | None:
        return self.dust.law if self.dust is not None else None

    @property
    def dust_info(self) -> dict | None:
        if self.dust is None:
            return None
        lo, hi = self.dust.applied_range_a
        return {
            "law": self.dust.law.key,
            "label": self.dust.law.label,
            "ebv": self.ebv,
            "rv": self.dust.rv,
            "a_v": self.dust.a_v,
            "applied_range_a": [lo, hi],
            "applied_range_obs_a": [lo * (1.0 + self.redshift), hi * (1.0 + self.redshift)],
            "frame": "rest",
            "extrapolated": False,
            "note": (
                "Foreground screen; applied only inside the law's validity window "
                "(rest frame); unchanged outside it."
            ),
        }

    @property
    def igm_info(self) -> dict | None:
        if self.igm_model is None:
            return None
        return igm_info(self.redshift, self.igm_model)

    @property
    def flux_unit(self) -> str:
        return (
            "erg/s/cm2/angstrom (observer frame at D_L)"
            if self.redshift > 0
            else "lsun_per_angstrom (rest frame)"
        )


def run_pipeline(
    wavelength_rest_a: np.ndarray,
    flux_lsun_a: np.ndarray,
    *,
    mass: float,
    dust_law: str | None,
    ebv: float,
    rv: float | None,
    z: float,
    igm: str | None,
) -> PipelineResult:
    """Apply mass → dust → redshift → IGM to one rest-frame SED.

    Raises ``HTTPException(422)`` for an unknown dust law / IGM model or an
    R_V outside the law's supported range.
    """
    wl_rest = np.asarray(wavelength_rest_a, dtype=float)
    flux = sedlib.scale_by_mass(np.asarray(flux_lsun_a, dtype=float), mass)

    dust: DustResult | None = None
    if dust_law and ebv > 0:
        if dust_law not in DUST_LAWS:
            raise HTTPException(422, f"unknown dust law '{dust_law}'")
        try:
            dust = apply_dust(wl_rest, flux, dust_law, ebv, rv)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        flux = dust.flux
    ebv_used = float(ebv) if dust is not None else 0.0

    igm_key = None if (not igm or igm == "none") else igm
    if igm_key is not None and igm_key not in IGM_MODELS:
        raise HTTPException(422, f"unknown IGM model '{igm_key}'")

    if z > 0:
        wl_obs, flux_obs = zlib.observe(wl_rest, flux, z)
        igm_factor = None
        if igm_key is not None:
            igm_factor = igm_transmission(wl_obs, z, igm_key)
            flux_obs = flux_obs * igm_factor
        return PipelineResult(
            wl_rest, flux, wl_obs, flux_obs, float(z), mass, dust, ebv_used, igm_key, igm_factor
        )

    # z = 0: rest frame, absolute-magnitude convention; the IGM does not apply.
    return PipelineResult(wl_rest, flux, wl_rest, flux, 0.0, mass, dust, ebv_used, None, None)


def filter_status(
    curve: FilterCurve,
    *,
    z: float,
    dust_law: DustLaw | None,
    dust_requested: bool,
    igm_requested: bool,
) -> dict:
    """Per-filter flags describing what was applied inside this passband.

    ``dust_status``: none | applied | partial | not_applied — judged by where the
    passband's support (converted to the rest frame) falls relative to the dust
    law's validity window.

    ``igm_status``: none | applied | not_applied — whether the passband reaches
    observed wavelengths below Lyα(1+z), and whether an IGM model was requested.

    ``attenuation_label``: human-readable summary built from the two.
    """
    lo_obs, hi_obs = curve.support
    stretch = 1.0 + max(z, 0.0)

    dust_status = DUST_STATUS_NONE
    if dust_requested and dust_law is not None:
        lo_rest, hi_rest = lo_obs / stretch, hi_obs / stretch
        win_lo, win_hi = dust_law.wavelength_range_a
        if hi_rest <= win_lo or lo_rest >= win_hi:
            dust_status = DUST_STATUS_NOT_APPLIED
        elif lo_rest >= win_lo and hi_rest <= win_hi:
            dust_status = DUST_STATUS_APPLIED
        else:
            dust_status = DUST_STATUS_PARTIAL

    igm_status = IGM_STATUS_NONE
    if z > 0 and lo_obs < LYMAN_ALPHA_A * stretch:
        igm_status = IGM_STATUS_APPLIED if igm_requested else IGM_STATUS_NOT_APPLIED

    dusty = dust_status in (DUST_STATUS_APPLIED, DUST_STATUS_PARTIAL)
    igmy = igm_status == IGM_STATUS_APPLIED
    if dusty and igmy:
        label = LABEL_BOTH
    elif dusty:
        label = LABEL_DUST
    elif igmy:
        label = LABEL_IGM
    else:
        label = LABEL_NEITHER
    return {"dust_status": dust_status, "igm_status": igm_status, "attenuation_label": label}
