"""Track geometry and serve-time preparation for the HR explorer.

Provides Eggleton (1983) Roche-lobe radii, physically-derived mass-loss rates
(finite differences of mass vs age — the raw sneplot rate columns are kept
only as flags/relative intensities because their absolute units are
ambiguous), and payload assembly with event-preserving decimation so tracks
stay light enough for the browser.
"""

from __future__ import annotations

import numpy as np

SECONDS_PER_YEAR = 3.155693e7
RSUN_PER_AU = 215.032


def eggleton_rl_fraction(q: np.ndarray | float) -> np.ndarray | float:
    """Roche-lobe radius / separation for mass ratio q = M_lobe / M_other.

    Eggleton (1983): R_L/a = 0.49 q^(2/3) / (0.6 q^(2/3) + ln(1 + q^(1/3))).
    Accurate to ~1% for all q.
    """
    q = np.asarray(q, dtype=float)
    q13 = np.cbrt(q)
    q23 = q13**2
    return 0.49 * q23 / (0.6 * q23 + np.log1p(q13))


def roche_radii_rsun(
    m1: np.ndarray, m2: np.ndarray, sep_rsun: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Roche-lobe radii (R_sun) of both stars for given masses and separation."""
    with np.errstate(divide="ignore", invalid="ignore"):
        q1 = m1 / m2
        rl1 = eggleton_rl_fraction(q1) * sep_rsun
        rl2 = eggleton_rl_fraction(1.0 / q1) * sep_rsun
    return rl1, rl2


def mass_loss_rate(age_yr: np.ndarray, mass: np.ndarray) -> np.ndarray:
    """|dM/dt| in Msun/yr from centred finite differences (>= 0)."""
    age = np.asarray(age_yr, dtype=float)
    m = np.asarray(mass, dtype=float)
    rate = np.zeros_like(m)
    if m.size < 2:
        return rate
    dm = np.gradient(m, age, edge_order=1)
    rate = np.abs(np.minimum(dm, 0.0))  # mass loss only
    rate[~np.isfinite(rate)] = 0.0
    return rate


def decimate_indices(n: int, target: int, keep: set[int] | None = None) -> np.ndarray:
    """Indices for downsampling a track to ~``target`` points.

    Always includes first/last and every index in ``keep`` (event steps),
    plus uniformly-spaced samples in between.
    """
    if n <= target:
        return np.arange(n)
    base = np.linspace(0, n - 1, target).astype(int)
    extra = np.asarray(sorted(keep or []), dtype=int)
    return np.unique(np.concatenate((base, extra, [0, n - 1])))
