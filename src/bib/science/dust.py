"""Dust attenuation/extinction of SEDs.

Laws are provided by the astropy-affiliated ``dust_extinction`` package.
Each law is only defined over a finite wavelength window; outside it we clamp
the curve at its boundary values (flat extrapolation) so the returned SED is
always finite. The validity window is returned with every result and the UI
shades the extrapolated regions — this behaviour is documented in the science
notes.
"""

from __future__ import annotations

from dataclasses import dataclass

import astropy.units as u
import numpy as np
from dust_extinction.averages import G03_SMCBar
from dust_extinction.parameter_averages import CCM89, F99


def _calzetti00_alav(x_inv_micron: np.ndarray, rv: float) -> np.ndarray:
    """Calzetti et al. (2000) starburst attenuation, A(λ)/A_V.

    k(λ) = 2.659(-1.857 + 1.040/λ) + R_V              for 0.63–2.20 µm
    k(λ) = 2.659(-2.156 + 1.509/λ - 0.198/λ² + 0.011/λ³) + R_V   for 0.12–0.63 µm
    A(λ)/A_V = k(λ)/R_V. Implemented directly (the dust_extinction package
    moved attenuation laws to a separate package); validated in tests.
    """
    x = np.asarray(x_inv_micron, dtype=float)
    k = np.where(
        x < 1.0 / 0.63,
        2.659 * (-1.857 + 1.040 * x) + rv,
        2.659 * (-2.156 + 1.509 * x - 0.198 * x**2 + 0.011 * x**3) + rv,
    )
    return np.clip(k, 0.0, None) / rv


@dataclass(frozen=True)
class DustLaw:
    key: str
    label: str
    note: str
    fixed_rv: float | None  # None = user-adjustable R_V
    default_rv: float
    x_min: float  # 1/micron
    x_max: float

    @property
    def wavelength_range_a(self) -> tuple[float, float]:
        """Valid wavelength window in Å (from the x range)."""
        return (1e4 / self.x_max, 1e4 / self.x_min)


DUST_LAWS: dict[str, DustLaw] = {
    "ccm89": DustLaw(
        "ccm89", "Milky Way — CCM89",
        "Cardelli, Clayton & Mathis (1989) Galactic extinction.",
        None, 3.1, 0.3, 10.0,
    ),
    "f99": DustLaw(
        "f99", "Milky Way — Fitzpatrick 99",
        "Fitzpatrick (1999) Galactic extinction.",
        None, 3.1, 0.3, 10.0,
    ),
    "calzetti00": DustLaw(
        "calzetti00", "Starburst — Calzetti 00",
        "Calzetti et al. (2000) attenuation for starburst galaxies.",
        4.05, 4.05, 0.455, 8.33,
    ),
    "smc": DustLaw(
        "smc", "SMC bar — Gordon 03",
        "Gordon et al. (2003) SMC bar average (steep UV, weak 2175 Å bump).",
        2.74, 2.74, 0.3, 10.0,
    ),
}


def _alav(law: DustLaw, rv: float, x_clamped: np.ndarray) -> np.ndarray:
    """A(λ)/A_V for the chosen law at (clamped) x in 1/micron."""
    x_q = x_clamped / u.micron
    if law.key == "ccm89":
        return np.asarray(CCM89(Rv=rv)(x_q), dtype=float)
    if law.key == "f99":
        return np.asarray(F99(Rv=rv)(x_q), dtype=float)
    if law.key == "calzetti00":
        return _calzetti00_alav(x_clamped, rv)
    if law.key == "smc":
        return np.asarray(G03_SMCBar()(x_q), dtype=float)
    raise KeyError(law.key)


@dataclass
class DustResult:
    flux: np.ndarray
    a_v: float
    rv: float
    law: DustLaw
    applied_range_a: tuple[float, float]  # window where the law is actually valid


def apply_dust(
    wavelength_a: np.ndarray,
    flux: np.ndarray,
    law_key: str,
    ebv: float,
    rv: float | None = None,
) -> DustResult:
    """Attenuate an SED by E(B-V) using the chosen law.

    Outside the law's validity window the extinction curve is clamped at its
    boundary value (flat extrapolation). E(B-V) <= 0 returns the input.
    """
    law = DUST_LAWS[law_key]
    rv_eff = law.fixed_rv if law.fixed_rv is not None else (rv or law.default_rv)
    if ebv <= 0:
        return DustResult(np.asarray(flux, dtype=float), 0.0, rv_eff, law, law.wavelength_range_a)

    x = 1e4 / np.asarray(wavelength_a, dtype=float)  # 1/micron
    # tiny margin keeps us strictly inside dust_extinction's bounds checks
    eps = 1e-6
    x_clamped = np.clip(x, law.x_min + eps, law.x_max - eps)
    a_lambda_over_av = _alav(law, rv_eff, x_clamped)
    a_v = rv_eff * ebv
    factor = 10.0 ** (-0.4 * a_lambda_over_av * a_v)
    return DustResult(
        flux=np.asarray(flux, dtype=float) * factor,
        a_v=a_v,
        rv=rv_eff,
        law=law,
        applied_range_a=law.wavelength_range_a,
    )
