"""Observer-frame transformation of BPASS SEDs.

Rest-frame BPASS SEDs are luminosity densities L_λ in L_sun/Å. For a source
at redshift z the observed flux density is

    f_λ(λ_obs) = L_λ(λ_rest) · L_sun / (4π D_L² (1+z)),   λ_obs = λ_rest (1+z)

with D_L the luminosity distance — the (1+z) factor accounts for bandwidth
stretching; D_L absorbs the remaining redshift factors, so the bolometric
flux is exactly L_bol / (4π D_L²).

Conventions:
  * z = 0 keeps the absolute-magnitude frame (source at 10 pc), matching the
    rest of bib.
  * Cosmology: flat ΛCDM with H0 = 70 km/s/Mpc, Ωm = 0.3 (stated in the UI).
  * Dust is applied in the *rest* frame before redshifting (dust at the
    source); foreground Milky Way extinction is out of scope.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from astropy.cosmology import FlatLambdaCDM

from bib.science.sed import L_SUN_ERG_S, PC_CM

COSMOLOGY = FlatLambdaCDM(H0=70.0, Om0=0.3)
COSMOLOGY_LABEL = "flat ΛCDM, H₀=70 km/s/Mpc, Ωm=0.3"

MAX_REDSHIFT = 20.0

_TEN_PC_CM = 10.0 * PC_CM


@lru_cache(maxsize=512)
def luminosity_distance_cm(z: float) -> float:
    """D_L in cm; z <= 0 returns the 10 pc absolute-magnitude convention."""
    if z <= 0:
        return _TEN_PC_CM
    return float(COSMOLOGY.luminosity_distance(z).to_value("cm"))


def luminosity_distance_mpc(z: float) -> float | None:
    """D_L in Mpc for display; None in the z = 0 absolute frame."""
    if z <= 0:
        return None
    return float(COSMOLOGY.luminosity_distance(z).to_value("Mpc"))


def observe(
    wavelength_rest_a: np.ndarray,
    flux_lsun_a: np.ndarray,
    z: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Transform a rest-frame SED (L_sun/Å) to observed f_λ (erg/s/cm²/Å).

    Returns (observed wavelength [Å], observed flux density). At z = 0 this
    is the flux from a source at 10 pc (absolute-magnitude frame).
    """
    d_cm = luminosity_distance_cm(z)
    area = 4.0 * np.pi * d_cm**2
    wl_obs = np.asarray(wavelength_rest_a, dtype=float) * (1.0 + z)
    f_lam = np.asarray(flux_lsun_a, dtype=float) * L_SUN_ERG_S / (area * (1.0 + z))
    return wl_obs, f_lam


def plot_level_lsun_a(f_lambda_cgs: float, z: float) -> float:
    """Convert an observed f_λ back to the SED Explorer's plot units.

    Returns L_λ(λ_rest)/(1+z) — the bandwidth-stretched luminosity density.
    The SED Explorer then multiplies by (10 pc/D_L)² so the on-screen curve
    includes distance dimming in the same L_sun/Å units as z = 0.
    """
    d_cm = luminosity_distance_cm(z)
    return f_lambda_cgs * 4.0 * np.pi * d_cm**2 / L_SUN_ERG_S
