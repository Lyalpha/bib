"""Foreground-screen extinction of an SED.

The spectrum is multiplied by 10^(-0.4 A_λ). That removes light from the
plotted SED. It is not a mixed star–dust attenuation, and the removed light
is not re-emitted. Laws are provided by the astropy-affiliated
``dust_extinction`` package. Each law is only defined over a finite wavelength
window. **No extrapolation is performed**: outside the window the SED is left
unextinguished (factor 1) and the validity window is returned with every result
so callers can flag affected wavelengths and photometry.
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
    rv_range: tuple[float, float] | None = None  # allowed R_V for adjustable laws

    @property
    def wavelength_range_a(self) -> tuple[float, float]:
        """Valid wavelength window in Å (from the x range)."""
        return (1e4 / self.x_max, 1e4 / self.x_min)

    def in_window(self, wavelength_a: np.ndarray) -> np.ndarray:
        """Boolean mask of wavelengths (Å) inside the law's validity window."""
        lo, hi = self.wavelength_range_a
        wl = np.asarray(wavelength_a, dtype=float)
        return (wl >= lo) & (wl <= hi)

    def resolve_rv(self, rv: float | None) -> float:
        """Effective R_V: fixed for single-R_V laws, else user value or default.

        Raises ``ValueError`` when an adjustable law is given an R_V outside
        ``rv_range`` (the range over which the parameterisation was fitted).
        """
        if self.fixed_rv is not None:
            return self.fixed_rv
        if rv is None:
            return self.default_rv
        if self.rv_range is not None and not (self.rv_range[0] <= rv <= self.rv_range[1]):
            raise ValueError(
                f"{self.label}: R_V={rv:g} outside the supported range "
                f"{self.rv_range[0]:g}–{self.rv_range[1]:g}"
            )
        return float(rv)


DUST_LAWS: dict[str, DustLaw] = {
    "ccm89": DustLaw(
        "ccm89",
        "Milky Way — CCM89",
        "Cardelli, Clayton & Mathis (1989) Galactic extinction.",
        None,
        3.1,
        0.3,
        10.0,
        rv_range=(2.0, 6.0),
    ),
    "f99": DustLaw(
        "f99",
        "Milky Way — Fitzpatrick 99",
        "Fitzpatrick (1999) Galactic extinction.",
        None,
        3.1,
        0.3,
        10.0,
        rv_range=(2.0, 6.0),
    ),
    "calzetti00": DustLaw(
        "calzetti00",
        "Starburst — Calzetti 00",
        "Calzetti et al. (2000) curve, applied here as a foreground screen on the SED.",
        4.05,
        4.05,
        0.455,
        8.33,
    ),
    "smc": DustLaw(
        "smc",
        "SMC bar — Gordon 03",
        "Gordon et al. (2003) SMC bar average (steep UV, weak 2175 Å bump).",
        2.74,
        2.74,
        0.3,
        10.0,
    ),
}


def _alav(law: DustLaw, rv: float, x_in_window: np.ndarray) -> np.ndarray:
    """A(λ)/A_V for the chosen law at x (1/micron) strictly inside its window."""
    x_q = x_in_window / u.micron
    if law.key == "ccm89":
        return np.asarray(CCM89(Rv=rv)(x_q), dtype=float)
    if law.key == "f99":
        return np.asarray(F99(Rv=rv)(x_q), dtype=float)
    if law.key == "calzetti00":
        return _calzetti00_alav(x_in_window, rv)
    if law.key == "smc":
        return np.asarray(G03_SMCBar()(x_q), dtype=float)
    raise KeyError(law.key)


@dataclass
class DustResult:
    flux: np.ndarray
    a_v: float
    rv: float
    law: DustLaw
    applied_range_a: tuple[float, float]  # window where the law is valid and was applied
    applied_mask: np.ndarray  # True where extinction was applied (inside the window)


def apply_dust(
    wavelength_a: np.ndarray,
    flux: np.ndarray,
    law_key: str,
    ebv: float,
    rv: float | None = None,
) -> DustResult:
    """Extinguish an SED by E(B-V): multiply by 10^(-0.4 A_λ) inside the law's window.

    Outside the law's validity window the curve is **not** extrapolated: the
    flux there is returned unchanged (factor 1) and ``applied_mask`` is False.
    E(B-V) <= 0 returns the input. Removed light is not re-emitted.

    Raises ``ValueError`` if R_V is outside the law's supported range.
    """
    law = DUST_LAWS[law_key]
    rv_eff = law.resolve_rv(rv)
    wl = np.asarray(wavelength_a, dtype=float)
    flux_in = np.asarray(flux, dtype=float)
    if ebv <= 0:
        return DustResult(
            flux_in, 0.0, rv_eff, law, law.wavelength_range_a, np.zeros(wl.shape, dtype=bool)
        )

    mask = law.in_window(wl)
    x = 1e4 / wl[mask]  # 1/micron
    # tiny margin keeps the window edges strictly inside dust_extinction's bounds checks
    eps = 1e-6
    x = np.clip(x, law.x_min + eps, law.x_max - eps)
    a_v = rv_eff * ebv
    factor = np.ones(wl.shape, dtype=float)
    if x.size:
        factor[mask] = 10.0 ** (-0.4 * _alav(law, rv_eff, x) * a_v)
    return DustResult(
        flux=flux_in * factor,
        a_v=a_v,
        rv=rv_eff,
        law=law,
        applied_range_a=law.wavelength_range_a,
        applied_mask=mask,
    )
