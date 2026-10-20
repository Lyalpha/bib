"""Intergalactic-medium (IGM) attenuation of a redshifted SED.

Neutral hydrogen along the line of sight absorbs rest-frame photons bluewards of
Lyman-α (1215.67 Å) through the Lyman series and the Lyman continuum. bib
applies the *mean* transmission ⟨e^{-τ_eff}⟩ as a multiplicative factor on the
observer-frame spectrum; it is a statistical average over sightlines, not the
absorption of any particular line of sight, and it does not include a damping
wing from a neutral IGM at z ≳ 6.

Two prescriptions are offered:

* ``inoue14`` — Inoue, Shimizu, Iwata & Tanaka (2014, MNRAS 442, 1805),
  eqs. 21–29 with the Table 2 coefficients, separating Lyman-α forest (LAF)
  and damped Lyman-α (DLA) contributions for 39 Lyman-series lines plus the
  Lyman continuum. This is the default and is the model used by most modern
  SED-fitting codes (e.g. eazy-py, Bagpipes).
* ``madau95`` — Madau (1995, ApJ 441, 18), the classic four-line Lyman-series
  fit (eq. 15) plus the Lyman-continuum approximation; retained for
  comparison with older work.

Transmission is 1 for λ_obs > λ_Lyα(1+z) and for z ≤ 0. Metal-line blanketing
is not modelled by either prescription.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LYMAN_ALPHA_A = 1215.67
LYMAN_LIMIT_A = 911.8  # Inoue+14 use 911.8 Å for the Lyman limit


@dataclass(frozen=True)
class IGMModel:
    key: str
    label: str
    note: str


IGM_MODELS: dict[str, IGMModel] = {
    "inoue14": IGMModel(
        "inoue14",
        "Inoue et al. (2014)",
        "Mean Lyman-series + Lyman-continuum transmission; LAF and DLA components.",
    ),
    "madau95": IGMModel(
        "madau95",
        "Madau (1995)",
        "Classic four-line Lyman-series fit plus Lyman-continuum approximation.",
    ),
}

# ---------------------------------------------------------------------------
# Inoue et al. (2014) Table 2: j, λ_j [Å], A_LAF^(1,2,3), A_DLA^(1,2)
# Transcribed from the published table (cross-checked against eazy-py and
# Bagpipes copies of the same table).
# ---------------------------------------------------------------------------
_INOUE14_TABLE2 = np.array(
    [
        # λ_j        A_LAF1       A_LAF2       A_LAF3       A_DLA1       A_DLA2
        [1215.670, 1.68976e-02, 2.35379e-03, 1.02611e-04, 1.61698e-04, 5.38995e-05],
        [1025.720, 4.69229e-03, 6.53625e-04, 2.84940e-05, 1.54539e-04, 5.15129e-05],
        [972.537, 2.23898e-03, 3.11884e-04, 1.35962e-05, 1.49767e-04, 4.99222e-05],
        [949.743, 1.31901e-03, 1.83735e-04, 8.00974e-06, 1.46031e-04, 4.86769e-05],
        [937.803, 8.70656e-04, 1.21280e-04, 5.28707e-06, 1.42893e-04, 4.76312e-05],
        [930.748, 6.17843e-04, 8.60640e-05, 3.75186e-06, 1.40159e-04, 4.67196e-05],
        [926.226, 4.60924e-04, 6.42055e-05, 2.79897e-06, 1.37714e-04, 4.59048e-05],
        [923.150, 3.56887e-04, 4.97135e-05, 2.16720e-06, 1.35495e-04, 4.51650e-05],
        [920.963, 2.84278e-04, 3.95992e-05, 1.72628e-06, 1.33452e-04, 4.44841e-05],
        [919.352, 2.31771e-04, 3.22851e-05, 1.40743e-06, 1.31561e-04, 4.38536e-05],
        [918.129, 1.92348e-04, 2.67936e-05, 1.16804e-06, 1.29785e-04, 4.32617e-05],
        [917.181, 1.62155e-04, 2.25878e-05, 9.84689e-07, 1.28117e-04, 4.27056e-05],
        [916.429, 1.38498e-04, 1.92925e-05, 8.41033e-07, 1.26540e-04, 4.21799e-05],
        [915.824, 1.19611e-04, 1.66615e-05, 7.26340e-07, 1.25041e-04, 4.16804e-05],
        [915.329, 1.04314e-04, 1.45306e-05, 6.33446e-07, 1.23614e-04, 4.12046e-05],
        [914.919, 9.17397e-05, 1.27791e-05, 5.57091e-07, 1.22248e-04, 4.07494e-05],
        [914.576, 8.12784e-05, 1.13219e-05, 4.93564e-07, 1.20938e-04, 4.03127e-05],
        [914.286, 7.25069e-05, 1.01000e-05, 4.40299e-07, 1.19681e-04, 3.98938e-05],
        [914.039, 6.50549e-05, 9.06198e-06, 3.95047e-07, 1.18469e-04, 3.94896e-05],
        [913.826, 5.86816e-05, 8.17421e-06, 3.56345e-07, 1.17298e-04, 3.90995e-05],
        [913.641, 5.31918e-05, 7.40949e-06, 3.23008e-07, 1.16167e-04, 3.87225e-05],
        [913.480, 4.84261e-05, 6.74563e-06, 2.94068e-07, 1.15071e-04, 3.83572e-05],
        [913.339, 4.42740e-05, 6.16726e-06, 2.68854e-07, 1.14011e-04, 3.80037e-05],
        [913.215, 4.06311e-05, 5.65981e-06, 2.46733e-07, 1.12983e-04, 3.76609e-05],
        [913.104, 3.73821e-05, 5.20723e-06, 2.27003e-07, 1.11972e-04, 3.73241e-05],
        [913.006, 3.45377e-05, 4.81102e-06, 2.09731e-07, 1.11002e-04, 3.70005e-05],
        [912.918, 3.19891e-05, 4.45601e-06, 1.94255e-07, 1.10051e-04, 3.66836e-05],
        [912.839, 2.97110e-05, 4.13867e-06, 1.80421e-07, 1.09125e-04, 3.63749e-05],
        [912.768, 2.76635e-05, 3.85346e-06, 1.67987e-07, 1.08220e-04, 3.60734e-05],
        [912.703, 2.58178e-05, 3.59636e-06, 1.56779e-07, 1.07337e-04, 3.57789e-05],
        [912.645, 2.41479e-05, 3.36374e-06, 1.46638e-07, 1.06473e-04, 3.54909e-05],
        [912.592, 2.26347e-05, 3.15296e-06, 1.37450e-07, 1.05629e-04, 3.52096e-05],
        [912.543, 2.12567e-05, 2.96100e-06, 1.29081e-07, 1.04802e-04, 3.49340e-05],
        [912.499, 1.99967e-05, 2.78549e-06, 1.21430e-07, 1.03991e-04, 3.46636e-05],
        [912.458, 1.88476e-05, 2.62543e-06, 1.14452e-07, 1.03198e-04, 3.43994e-05],
        [912.420, 1.77928e-05, 2.47850e-06, 1.08047e-07, 1.02420e-04, 3.41402e-05],
        [912.385, 1.68222e-05, 2.34330e-06, 1.02153e-07, 1.01657e-04, 3.38856e-05],
        [912.353, 1.59286e-05, 2.21882e-06, 9.67268e-08, 1.00908e-04, 3.36359e-05],
        [912.324, 1.50996e-05, 2.10334e-06, 9.16925e-08, 1.00168e-04, 3.33895e-05],
    ]
)
_I14_LAM = _INOUE14_TABLE2[:, 0][:, None]
_I14_LAF1 = _INOUE14_TABLE2[:, 1][:, None]
_I14_LAF2 = _INOUE14_TABLE2[:, 2][:, None]
_I14_LAF3 = _INOUE14_TABLE2[:, 3][:, None]
_I14_DLA1 = _INOUE14_TABLE2[:, 4][:, None]
_I14_DLA2 = _INOUE14_TABLE2[:, 5][:, None]


def _inoue14_tau(lobs: np.ndarray, z: float) -> np.ndarray:
    """Effective optical depth τ_eff(λ_obs) of Inoue+14 for λ_obs below Lyα(1+z)."""
    zp1 = 1.0 + z
    # --- Lyman series: LAF (eq. 21) -------------------------------------
    ratio = lobs[None, :] / _I14_LAM  # (39, N) = λ_obs / λ_j = 1 + z_abs
    below_source = ratio < zp1  # absorber must be in front of the source
    tau_ls = np.zeros_like(ratio)
    r1 = below_source & (ratio < 2.2)
    r2 = below_source & (ratio >= 2.2) & (ratio < 5.7)
    r3 = below_source & (ratio >= 5.7)
    tau_ls += np.where(r1, _I14_LAF1 * ratio**1.2, 0.0)
    tau_ls += np.where(r2, _I14_LAF2 * ratio**3.7, 0.0)
    tau_ls += np.where(r3, _I14_LAF3 * ratio**5.5, 0.0)
    # --- Lyman series: DLA (eq. 22) -------------------------------------
    d1 = below_source & (ratio < 3.0)
    d2 = below_source & (ratio >= 3.0)
    tau_ls += np.where(d1, _I14_DLA1 * ratio**2.0, 0.0)
    tau_ls += np.where(d2, _I14_DLA2 * ratio**3.0, 0.0)
    tau = tau_ls.sum(axis=0)

    # --- Lyman continuum --------------------------------------------------
    x = lobs / LYMAN_LIMIT_A  # 1 + z_abs at the Lyman limit
    lc = x < zp1
    tau_lc = np.zeros_like(lobs)
    xl = x[lc]
    # DLA component (eqs. 28–29)
    if z < 2.0:
        t = 0.2113 * zp1**2.0 - 0.07661 * zp1**2.3 * xl ** (-0.3) - 0.1347 * xl**2.0
    else:
        t = np.where(
            xl >= 3.0,
            0.04696 * zp1**3.0 - 0.01779 * zp1**3.3 * xl ** (-0.3) - 0.02916 * xl**3.0,
            0.6340
            + 0.04696 * zp1**3.0
            - 0.01779 * zp1**3.3 * xl ** (-0.3)
            - 0.1347 * xl**2.0
            - 0.2905 * xl ** (-0.3),
        )
    tau_lc[lc] += t
    # LAF component (eqs. 25–27)
    if z < 1.2:
        t = 0.3248 * (xl**1.2 - zp1 ** (-0.9) * xl**2.1)
    elif z < 4.7:
        t = np.where(
            xl >= 2.2,
            2.545e-2 * (zp1**1.6 * xl**2.1 - xl**3.7),
            2.545e-2 * zp1**1.6 * xl**2.1 + 0.3248 * xl**1.2 - 0.2496 * xl**2.1,
        )
    else:
        t = np.where(
            xl >= 5.7,
            5.221e-4 * (zp1**3.4 * xl**2.1 - xl**5.5),
            np.where(
                xl >= 2.2,
                5.221e-4 * zp1**3.4 * xl**2.1 + 0.2182 * xl**2.1 - 2.545e-2 * xl**3.7,
                5.221e-4 * zp1**3.4 * xl**2.1 + 0.3248 * xl**1.2 - 3.140e-2 * xl**2.1,
            ),
        )
    tau_lc[lc] += t
    return tau + np.clip(tau_lc, 0.0, None)


# ---------------------------------------------------------------------------
# Madau (1995)
# ---------------------------------------------------------------------------
# Lyman-series coefficients A_j (eq. 15): Lyα, Lyβ, Lyγ, Lyδ.
_M95_LINES = np.array([[1215.67, 0.0036], [1025.72, 0.0017], [972.537, 0.0012], [949.743, 0.00093]])
_M95_LIMIT_A = 912.0


def _madau95_tau(lobs: np.ndarray, z: float) -> np.ndarray:
    zp1 = 1.0 + z
    tau = np.zeros_like(lobs)
    for lam_j, a_j in _M95_LINES:
        mask = lobs < lam_j * zp1
        tau[mask] += a_j * (lobs[mask] / lam_j) ** 3.46
    # Lyman continuum (Madau 1995 eq. 16, analytic approximation)
    lc = lobs < _M95_LIMIT_A * zp1
    xc = lobs[lc] / _M95_LIMIT_A
    xe = zp1
    tau[lc] += (
        0.25 * xc**3.0 * (xe**0.46 - xc**0.46)
        + 9.4 * xc**1.5 * (xe**0.18 - xc**0.18)
        - 0.7 * xc**3.0 * (xc**-1.32 - xe**-1.32)
        - 0.023 * (xe**1.68 - xc**1.68)
    )
    return np.clip(tau, 0.0, None)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def igm_transmission(wl_obs_a: np.ndarray, z: float, model: str = "inoue14") -> np.ndarray:
    """Mean IGM transmission e^{-τ_eff} on an observer-frame wavelength grid (Å).

    Returns an array of ones for ``z <= 0``. Raises ``KeyError`` for an
    unknown model key.
    """
    if model not in IGM_MODELS:
        raise KeyError(model)
    lobs = np.asarray(wl_obs_a, dtype=float)
    trans = np.ones(lobs.shape, dtype=float)
    if z <= 0:
        return trans
    affected = lobs < LYMAN_ALPHA_A * (1.0 + z)
    if not affected.any():
        return trans
    lo = lobs[affected]
    tau = _inoue14_tau(lo, z) if model == "inoue14" else _madau95_tau(lo, z)
    trans[affected] = np.exp(-tau)
    return trans


def apply_igm(wl_obs_a: np.ndarray, flux_obs: np.ndarray, z: float, model: str) -> np.ndarray:
    """Multiply an observer-frame SED by the IGM transmission."""
    return np.asarray(flux_obs, dtype=float) * igm_transmission(wl_obs_a, z, model)


def igm_info(z: float, model: str) -> dict:
    """Serialisable description of the IGM prescription applied at redshift ``z``."""
    spec = IGM_MODELS[model]
    return {
        "model": spec.key,
        "label": spec.label,
        "lyman_alpha_obs_a": LYMAN_ALPHA_A * (1.0 + z),
        "lyman_limit_obs_a": LYMAN_LIMIT_A * (1.0 + z),
    }
