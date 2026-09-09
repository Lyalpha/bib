"""Synthetic demonstration dataset.

``bib demo-seed`` fills the database with a clearly-labelled toy dataset so the
interface can be explored with zero downloads. Shapes are physically plausible
(blackbody-mixture SEDs, toy isochrones and evolution tracks) but carry **no
scientific content** — every row is flagged ``is_synthetic`` and the UI shows a
persistent warning banner while any synthetic data exist.

The generator deliberately exercises the whole schema: multiple IMF labels,
sin/bin populations, alpha-enhancement variants, per-age product tables,
HRD density grids, and stellar tracks that trigger every event heuristic
(RLOF, common envelope, WR stripping, thermal pulses...).
"""

from __future__ import annotations

import numpy as np
from rich.console import Console
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from bib.db import models as m
from bib.db.session import session_scope
from bib.ingest.parsers import ALPHA_VALUES, Z_VALUES, ModelName, TrackData
from bib.ingest.run import _get_or_create_grid, _insert_model, _insert_product_rows
from bib.science import sed as sedlib

RELEASE_VERSION = "demo"

# physical constants (cgs)
H_ERG_S = 6.62607015e-27
C_CM_S = 2.99792458e10
K_ERG_K = 1.380649e-16
C_A_S = C_CM_S * 1e8  # Å/s
JY = 1.0e-23  # erg/s/cm^2/Hz


# ---------------------------------------------------------------------------
# toy SED synthesis
# ---------------------------------------------------------------------------


def _wavelength_grid(n: int = 16384) -> np.ndarray:
    return np.logspace(0.0, 5.0, n)  # 1 Å … 100,000 Å


def _blackbody_l_lambda(wl_a: np.ndarray, t_k: float) -> np.ndarray:
    """Unnormalised Planck L_lambda on an Å grid (arbitrary units)."""
    wl_cm = wl_a * 1e-8
    x = H_ERG_S * C_CM_S / (wl_cm * K_ERG_K * t_k)
    x = np.clip(x, 1e-6, 700.0)
    return wl_cm**-5 / np.expm1(x)


def _component(wl: np.ndarray, t_k: float, l_bol_lsun: float) -> np.ndarray:
    shape = _blackbody_l_lambda(wl, t_k)
    norm = np.trapezoid(shape, wl)
    return shape * (l_bol_lsun / norm)


def synth_sed(
    wl: np.ndarray, log_age: float, z_value: float, binary: bool, alpha: float = 0.0,
    imf_hardness: float = 1.0,
) -> np.ndarray:
    """Toy SSP SED in L_sun/Å for 1e6 Msun formed. Illustrative only."""
    age = 10.0**log_age
    zfac = (max(z_value, 1e-5) / 0.020) ** -0.045  # metal-poor => hotter

    # main-sequence turnoff component
    t_to = 42000.0 * (age / 1e6) ** -0.24 * zfac * imf_hardness
    t_to = float(np.clip(t_to, 3800.0, 55000.0))
    l_bol = 10.0 ** (9.55 - 0.82 * (log_age - 6.0))  # fading population
    l_bol = max(l_bol, 10.0**6.1)

    frac_giants = float(np.clip((log_age - 6.8) / 4.2, 0.0, 0.62))
    sed = _component(wl, t_to, l_bol * (1.0 - frac_giants))
    sed += _component(wl, 3900.0 * zfac**0.5, l_bol * frac_giants)

    if log_age < 6.9:  # very young: hot WR-ish tail
        sed += _component(wl, 9.0e4, l_bol * 0.06 * (6.9 - log_age))

    if binary and 6.9 < log_age < 8.8:  # stripped stars keep old pops blue
        strength = 0.10 * np.exp(-0.5 * ((log_age - 7.7) / 0.6) ** 2)
        sed += _component(wl, 3.2e4, l_bol * strength)

    if alpha:  # tiny alpha-enhancement tilt in the UV (demo affordance)
        tilt = 1.0 + alpha * 0.25 * np.clip((3000.0 - wl) / 3000.0, 0.0, 1.0)
        sed = sed * tilt

    return sed


# ---------------------------------------------------------------------------
# derived per-age products (computed from the toy SEDs)
# ---------------------------------------------------------------------------

_BOXCAR_BANDS: dict[str, tuple[float, float]] = {
    # crude central/half-width boxcars, Å — demo data only
    "mag_u": (3600, 300), "mag_b": (4400, 490), "mag_v": (5500, 440),
    "mag_r": (6400, 700), "mag_i": (7900, 750), "mag_j": (12350, 810),
    "mag_h": (16620, 1255), "mag_k": (21590, 1310),
    "sdss_u": (3551, 300), "sdss_g": (4686, 700), "sdss_r": (6165, 620),
    "sdss_i": (7481, 650), "sdss_z": (8931, 700),
    "f300w": (2987, 370), "f336w": (3344, 190), "f435w": (4297, 500),
    "f450w": (4520, 480), "f555w": (5336, 600), "f606w": (5887, 750),
    "f814w": (7940, 870),
}


def _boxcar_ab_mag(wl: np.ndarray, flux_lsun_a: np.ndarray, centre: float, half: float) -> float:
    sel = (wl >= centre - half) & (wl <= centre + half)
    if not np.any(sel):
        return float("nan")
    f_lambda = sedlib.flux_at_10pc(flux_lsun_a[sel])  # erg/s/cm^2/Å
    f_nu = f_lambda * (wl[sel] ** 2) / C_A_S  # erg/s/cm^2/Hz
    mean = float(np.trapezoid(f_nu, wl[sel]) / np.trapezoid(np.ones_like(f_nu), wl[sel]))
    return -2.5 * float(np.log10(max(mean, 1e-300) / (3631.0 * JY)))


def _bin_width_yr(age_index: int) -> float:
    la = sedlib.BPASS_LOG_AGES[age_index]
    if age_index == 0:
        return 10.0**6.05
    return 10.0 ** (la + 0.05) - 10.0 ** (la - 0.05)


def _derived_tables(wl: np.ndarray, seds: np.ndarray, binary: bool) -> dict[str, np.ndarray]:
    """Build colours/ionizing/starmass/supernova/yields/mlratio arrays (51 rows)."""
    ages = sedlib.BPASS_LOG_AGES
    n = ages.size

    colours = np.zeros((n, 22))
    ionizing = np.zeros((n, 5))
    starmass = np.zeros((n, 3 if binary else 2))
    supernova = np.zeros((n, 18))
    yields = np.zeros((n, 9))
    mlratio = np.zeros((n, 3))

    for i, la in enumerate(ages):
        flux = seds[i]
        mags = {name: _boxcar_ab_mag(wl, flux, c, h) for name, (c, h) in _BOXCAR_BANDS.items()}
        colours[i, 0] = la
        colours[i, 1] = mags["mag_v"] - mags["mag_i"]
        for j, name in enumerate(
            ["mag_u", "mag_b", "mag_v", "mag_r", "mag_i", "mag_j", "mag_h", "mag_k",
             "sdss_u", "sdss_g", "sdss_r", "sdss_i", "sdss_z",
             "f300w", "f336w", "f435w", "f450w", "f555w", "f606w", "f814w"],
            start=2,
        ):
            colours[i, j] = mags[name]

        # ionizing photons below 912 Å
        sel = wl < 912.0
        f_erg = flux[sel] * sedlib.L_SUN_ERG_S  # erg/s/Å
        nion = np.trapezoid(f_erg * wl[sel] * 1e-8 / (H_ERG_S * C_CM_S), wl[sel])
        log_nion = float(np.log10(max(nion, 1e30)))
        fuv = (wl >= 1556) & (wl <= 1576)
        nuv = (wl >= 2257) & (wl <= 2277)
        ionizing[i] = [
            la,
            log_nion,
            log_nion - 11.87,
            float(np.log10(np.mean(flux[fuv]) * sedlib.L_SUN_ERG_S)),
            float(np.log10(np.mean(flux[nuv]) * sedlib.L_SUN_ERG_S)),
        ]

        live = 1e6 * (0.995 - 0.44 * np.clip((la - 6.0) / 5.0, 0, 1) ** 0.75)
        starmass[i, 0] = la
        starmass[i, 1] = live
        if binary:
            starmass[i, 2] = 1e6 * 0.11 * np.clip((la - 6.6) / 4.4, 0, 1) ** 0.8

        dt = _bin_width_yr(i)
        n_iip = 6500.0 * np.exp(-0.5 * ((la - 7.05) / 0.28) ** 2)
        n_ib = 900.0 * np.exp(-0.5 * ((la - 6.75) / 0.22) ** 2) * (1.6 if binary else 1.0)
        n_ic = 600.0 * np.exp(-0.5 * ((la - 6.65) / 0.20) ** 2) * (1.5 if binary else 1.0)
        n_ia = 2200.0 * (10.0 ** (la - 9.0)) ** -0.55 if (binary and la >= 7.9) else 0.0
        n_low = 350.0 * np.exp(-0.5 * ((la - 9.3) / 0.5) ** 2) if binary else 0.0
        row = [la, n_ia, n_iip, 0.35 * n_iip, n_ib, n_ic,
               0.004 * n_ic if binary else 0.0, 0.0, n_low]
        errors = [np.sqrt(max(v, 0.0)) for v in row[1:]]
        supernova[i] = row + errors + [dt]

        wind_scale = 10.0 ** (-0.9 * (la - 6.0))
        yields[i] = [
            la,
            0.011 * wind_scale, 0.004 * wind_scale, 0.0011 * wind_scale,
            2.4e11 * wind_scale,
            (n_iip + n_ib + n_ic + n_ia) / dt * 1.0e44,
            0.006 * wind_scale, 0.0026 * wind_scale, 0.0009 * wind_scale,
        ]

        lv = 10.0 ** (-0.4 * (colours[i, 4] - 4.80))  # L_V/Lsun_V from abs V mag
        lk = 10.0 ** (-0.4 * (colours[i, 9] - 3.27))
        mlratio[i] = [la, live / max(lk, 1.0), live / max(lv, 1.0)]

    return {
        "colours": colours, "ionizing": ionizing, "starmass": starmass,
        "supernova": supernova, "yields": yields, "mlratio": mlratio,
    }


# ---------------------------------------------------------------------------
# toy HRD density grids
# ---------------------------------------------------------------------------


def _splat(grid: np.ndarray, log_t: float, log_l: float, weight: float, sigma: float = 1.4) -> None:
    """Add a gaussian blob to a (logT-row, logL-col) occupation grid."""
    row = (log_t - 0.1) / 0.1
    col = (log_l + 2.9) / 0.1
    r0, c0 = round(row), round(col)
    size = 4
    for r in range(max(0, r0 - size), min(100, r0 + size + 1)):
        for c in range(max(0, c0 - size), min(100, c0 + size + 1)):
            d2 = (r - row) ** 2 + (c - col) ** 2
            grid[r, c] += weight * np.exp(-0.5 * d2 / sigma**2)


def synth_hrd_grids(log_age: float, binary: bool) -> np.ndarray:
    """(3 h_classes, 100, 100) toy occupation grids for the TL diagram."""
    grids = np.zeros((3, 100, 100), dtype=np.float64)
    age = 10.0**log_age
    logt_to = float(np.clip(np.log10(42000.0 * (age / 1e6) ** -0.24), 3.60, 4.72))
    logl_to = 4.9 - 1.05 * (log_age - 6.0)

    # main sequence ridge from the turnoff downward
    for frac in np.linspace(0.0, 1.0, 26):
        lt = logt_to - frac * (logt_to - 3.52)
        ll = logl_to - frac * (logl_to + 2.6)
        _splat(grids[0], lt, ll, weight=10.0 * (0.25 + frac) ** 1.6)

    if log_age > 6.9:  # giants
        _splat(grids[0], 3.62, logl_to + 1.1, weight=26.0, sigma=2.2)
        _splat(grids[0], 3.68, logl_to + 0.6, weight=13.0, sigma=1.8)

    if binary and 6.9 < log_age < 8.8:  # stripped hot stars
        strength = 30.0 * np.exp(-0.5 * ((log_age - 7.7) / 0.6) ** 2)
        _splat(grids[1], 4.65, logl_to + 0.4, weight=strength, sigma=1.6)
        _splat(grids[2], 4.85, logl_to + 0.1, weight=0.5 * strength, sigma=1.4)

    return grids


# ---------------------------------------------------------------------------
# toy stellar tracks
# ---------------------------------------------------------------------------

_ZAMS_MASS = np.array([0.8, 1.0, 2.0, 3.0, 5.0, 8.0, 15.0, 30.0, 60.0, 120.0])
_ZAMS_LOGT = np.array([3.71, 3.76, 3.95, 4.10, 4.25, 4.35, 4.49, 4.64, 4.73, 4.78])
_ZAMS_LOGL = np.array([-0.60, 0.00, 1.20, 1.90, 2.80, 3.60, 4.25, 5.10, 5.70, 6.15])
_LOG_T_SUN = 3.7617


def _zams(m1: float) -> tuple[float, float]:
    lt = float(np.interp(np.log10(m1), np.log10(_ZAMS_MASS), _ZAMS_LOGT))
    ll = float(np.interp(np.log10(m1), np.log10(_ZAMS_MASS), _ZAMS_LOGL))
    return lt, ll


def _t_ms(m1: float) -> float:
    return 1.0e10 * m1**-2.5 + 3.0e6


def _log_r(log_l: np.ndarray, log_t: np.ndarray) -> np.ndarray:
    return 0.5 * np.asarray(log_l) - 2.0 * (np.asarray(log_t) - _LOG_T_SUN)


def _kepler_log_sep(m_tot: float, period_days: float) -> float:
    return float(np.log10(4.208 * (m_tot * period_days**2) ** (1.0 / 3.0)))


def _period_days(m_tot: float, log_sep: float) -> float:
    a = 10.0**log_sep
    return float(np.sqrt(a**3 / (4.208**3 * m_tot)))


class _TrackBuilder:
    """Accumulates track segments into sneplot-like column arrays."""

    def __init__(self) -> None:
        self.rows: dict[str, list[float]] = {
            k: []
            for k in [
                "step", "age_yr", "log_r1", "log_t1", "log_l1", "m1",
                "he_core", "co_core", "one_core",
                "x_surf", "y_surf", "c_surf", "n_surf", "o_surf", "ne_surf",
                "dm1w", "dm2w", "dm1a", "dm2a", "dm1r", "dm2r",
                "period_yr", "log_sep", "m2", "log_r2", "log_t2", "log_l2",
            ]
        }

    def add(self, **kw: float) -> None:
        r = self.rows
        i = len(r["step"])
        log_t = kw["log_t1"]
        log_l = kw["log_l1"]
        r["step"].append(float(i))
        r["age_yr"].append(kw["age_yr"])
        r["log_t1"].append(log_t)
        r["log_l1"].append(log_l)
        r["log_r1"].append(kw.get("log_r1", float(_log_r(log_l, log_t))))
        r["m1"].append(kw["m1"])
        r["he_core"].append(kw.get("he_core", 0.0))
        r["co_core"].append(kw.get("co_core", 0.0))
        r["one_core"].append(kw.get("one_core", 0.0))
        r["x_surf"].append(kw.get("x_surf", 0.70))
        r["y_surf"].append(kw.get("y_surf", 0.28))
        r["c_surf"].append(kw.get("c_surf", 0.003))
        r["n_surf"].append(kw.get("n_surf", 0.001))
        r["o_surf"].append(kw.get("o_surf", 0.008))
        r["ne_surf"].append(kw.get("ne_surf", 0.002))
        for key in ("dm1w", "dm2w", "dm1a", "dm2a", "dm1r", "dm2r"):
            r[key].append(kw.get(key, 0.0))
        m2 = kw.get("m2", np.nan)
        r["m2"].append(m2)
        log_sep = kw.get("log_sep", np.nan)
        r["log_sep"].append(log_sep)
        if np.isfinite(log_sep) and np.isfinite(m2):
            r["period_yr"].append(_period_days(kw["m1"] + m2, log_sep) / 365.25)
        else:
            r["period_yr"].append(kw.get("period_yr", np.nan))
        r["log_r2"].append(kw.get("log_r2", np.nan))
        r["log_t2"].append(kw.get("log_t2", np.nan))
        r["log_l2"].append(kw.get("log_l2", np.nan))

    def build(self) -> TrackData:
        return TrackData(columns={k: np.asarray(v, dtype=np.float64) for k, v in self.rows.items()})


def _ms_segment(b: _TrackBuilder, m1: float, t_end: float, n: int = 160, **binary: float) -> None:
    lt0, ll0 = _zams(m1)
    for f in np.linspace(0.0, 1.0, n):
        b.add(
            age_yr=f * t_end,
            log_t1=lt0 - 0.05 * f,
            log_l1=ll0 + 0.28 * f,
            m1=m1 * (1.0 - 0.02 * f),
            x_surf=0.70,
            dm1w=1e-9 * m1,
            **binary,
        )


def toy_single(m1: float) -> TrackData:
    b = _TrackBuilder()
    tms = _t_ms(m1)
    _ms_segment(b, m1, tms)
    lt_tams = _zams(m1)[0] - 0.05
    ll_tams = _zams(m1)[1] + 0.28
    m_now = m1 * 0.98
    he0 = 0.12 * m1

    if m1 < 9.0:  # RGB -> He burning -> AGB with thermal pulses
        t_rgb = 0.12 * tms
        ll_tip = min(ll_tams + 2.4, 3.5)
        for f in np.linspace(0.0, 1.0, 90):
            b.add(
                age_yr=tms + f * t_rgb,
                log_t1=lt_tams + (3.61 - lt_tams) * f,
                log_l1=ll_tams + (ll_tip - ll_tams) * f**1.3,
                m1=m_now - 0.06 * m1 * f,
                he_core=he0 * (0.4 + 0.6 * f),
                dm1w=2e-8 * m1 * (1 + 8 * f),
            )
        m_now -= 0.06 * m1
        t_heb = 0.10 * tms
        lt_heb = 3.72 if m1 < 2.2 else 3.80
        for f in np.linspace(0.0, 1.0, 60):
            b.add(
                age_yr=tms + t_rgb + f * t_heb,
                log_t1=3.61 + (lt_heb - 3.61) * np.sin(np.pi * f) * 0.9,
                log_l1=ll_tip - 0.7 + 0.15 * f,
                m1=m_now,
                he_core=he0,
                co_core=0.02 * m1 * f,
                dm1w=1e-8 * m1,
            )
        t_agb = 0.03 * tms
        ll_agb_tip = min(ll_tip + 1.1, 4.4)
        for f in np.linspace(0.0, 1.0, 110):
            pulse = 0.10 * np.sin(2 * np.pi * 9 * f) * f
            b.add(
                age_yr=tms + t_rgb + t_heb + f * t_agb,
                log_t1=3.58 - 0.04 * f,
                log_l1=(ll_tip - 0.55) + (ll_agb_tip - ll_tip + 0.55) * f + pulse,
                m1=m_now - (m_now - 0.55 * m1**0.4) * f**1.6,
                he_core=he0,
                co_core=0.02 * m1 + (0.5 * m1**0.5 - 0.02 * m1) * f * 0.5,
                x_surf=0.70 - 0.05 * f,
                dm1w=3e-7 * m1 * (1 + 20 * f**2),
            )
    else:  # massive: RSG excursion then (for the most massive) WR stripping
        t_post = 0.08 * tms
        for f in np.linspace(0.0, 1.0, 70):
            b.add(
                age_yr=tms + f * t_post,
                log_t1=lt_tams + (3.56 - lt_tams) * f**0.7,
                log_l1=ll_tams + 0.25 * f,
                m1=m_now - 0.12 * m1 * f,
                he_core=he0 * (0.5 + 0.5 * f),
                dm1w=5e-7 * m1 * (1 + 6 * f),
            )
        m_now -= 0.12 * m1
        if m1 >= 25.0:  # WR phase
            t_wr = 0.04 * tms
            for f in np.linspace(0.0, 1.0, 70):
                b.add(
                    age_yr=tms + t_post + f * t_wr,
                    log_t1=3.56 + (4.95 - 3.56) * f**0.5,
                    log_l1=ll_tams + 0.25 - 0.15 * f,
                    m1=m_now - (m_now - 0.35 * m1**0.75) * f,
                    he_core=he0,
                    co_core=0.25 * he0 * f,
                    one_core=0.05 * he0 * max(f - 0.8, 0.0) / 0.2,
                    x_surf=max(0.70 - 1.3 * f, 0.02),
                    y_surf=min(0.28 + 1.1 * f, 0.9),
                    dm1w=1e-5 * (1 + 10 * f),
                )
        else:
            t_heb = 0.08 * tms
            for f in np.linspace(0.0, 1.0, 60):
                b.add(
                    age_yr=tms + t_post + f * t_heb,
                    log_t1=3.56 + 0.10 * np.sin(np.pi * f),
                    log_l1=ll_tams + 0.25 + 0.15 * f,
                    m1=m_now - 0.05 * m1 * f,
                    he_core=he0,
                    co_core=0.4 * he0 * f,
                    one_core=0.08 * he0 * max(f - 0.85, 0.0) / 0.15,
                    dm1w=2e-6 * m1,
                )
    return b.build()


def toy_close_binary() -> TrackData:
    """15 + 9 Msun, logP=0.6: case-B RLOF strips the primary to a helium star."""
    b = _TrackBuilder()
    m1, m2 = 15.0, 9.0
    tms = _t_ms(m1)
    log_sep0 = _kepler_log_sep(m1 + m2, 10.0 ** (0.6))
    _ms_segment(
        b, m1, 0.96 * tms, n=140,
        m2=m2, log_sep=log_sep0, log_t2=4.36, log_l2=3.72, log_r2=0.62,
    )
    lt, ll = _zams(m1)[0] - 0.05, _zams(m1)[1] + 0.28
    # RLOF: rapid envelope loss, companion accretes, orbit shrinks then widens
    t_rlof = 0.035 * tms
    for f in np.linspace(0.0, 1.0, 90):
        m1_now = m1 * 0.98 - (m1 * 0.98 - 4.6) * f**1.2
        m2_now = m2 + 3.9 * f
        sep = log_sep0 - 0.10 * np.sin(np.pi * min(f * 1.4, 1.0)) + 0.32 * f**2
        b.add(
            age_yr=0.96 * tms + f * t_rlof,
            log_t1=lt + (3.95 - lt) * np.sin(np.pi * f) * 0.5 + (4.35 - lt) * f**3,
            log_l1=ll + 0.35 * f - 0.25 * np.sin(np.pi * f),
            m1=m1_now,
            he_core=0.12 * m1 * (0.4 + 0.6 * f),
            x_surf=0.70 - 0.45 * f,
            y_surf=0.28 + 0.42 * f,
            dm1r=6e-6 * np.sin(np.pi * min(f * 1.2, 1.0)) + 1e-7,
            dm2a=3e-6 * np.sin(np.pi * min(f * 1.2, 1.0)) + 5e-8,
            m2=m2_now,
            log_sep=sep,
            log_t2=4.36 + 0.10 * f,
            log_l2=3.72 + 0.55 * f,
            log_r2=0.62 + 0.18 * f,
        )
    # stripped helium star
    t_he = 1.6e6
    sep_end = log_sep0 + 0.22
    for f in np.linspace(0.0, 1.0, 80):
        b.add(
            age_yr=0.96 * tms + t_rlof + f * t_he,
            log_t1=4.35 + (4.88 - 4.35) * f**0.6,
            log_l1=4.32 - 0.10 * f,
            m1=4.6 - 0.5 * f,
            he_core=4.0,
            co_core=2.3 * f,
            one_core=0.4 * max(f - 0.85, 0.0) / 0.15,
            x_surf=0.05,
            y_surf=0.90,
            dm1w=4e-6,
            m2=12.9,
            log_sep=sep_end + 0.05 * f,
            log_t2=4.47, log_l2=4.28, log_r2=0.80,
        )
    return b.build()


def toy_wide_binary() -> TrackData:
    """15 + 9 Msun, logP=3.0: effectively single evolution — contrast case."""
    single = toy_single(15.0)
    n = single.n_steps
    log_sep = np.full(n, _kepler_log_sep(24.0, 10.0**3.0))
    # orbit widens slightly as winds remove mass
    log_sep += 0.10 * (15.0 - single["m1"]) / 15.0
    single.columns["m2"] = np.full(n, 9.0)
    single.columns["log_sep"] = log_sep
    single.columns["period_yr"] = np.array(
        [_period_days(m + 9.0, s) / 365.25 for m, s in zip(single["m1"], log_sep, strict=True)]
    )
    single.columns["log_t2"] = np.full(n, 4.36)
    single.columns["log_l2"] = np.full(n, 3.72)
    single.columns["log_r2"] = np.full(n, 0.62)
    return single


def toy_cee_binary() -> TrackData:
    """5 + 2.5 Msun, logP=0.4: unstable RLOF on the giant branch -> common envelope."""
    b = _TrackBuilder()
    m1, m2 = 5.0, 2.5
    tms = _t_ms(m1)
    log_sep0 = _kepler_log_sep(m1 + m2, 10.0**0.4)
    _ms_segment(b, m1, tms, n=120, m2=m2, log_sep=log_sep0, log_t2=4.05, log_l2=1.55, log_r2=0.28)
    lt, ll = _zams(m1)[0] - 0.05, _zams(m1)[1] + 0.28
    t_rgb = 0.05 * tms
    for f in np.linspace(0.0, 1.0, 60):  # expand towards RLOF
        b.add(
            age_yr=tms + f * t_rgb,
            log_t1=lt + (3.62 - lt) * f,
            log_l1=ll + 1.1 * f**1.2,
            m1=m1 * 0.98,
            he_core=0.6 * (0.5 + 0.5 * f),
            m2=m2, log_sep=log_sep0,
            log_t2=4.05, log_l2=1.55, log_r2=0.28,
        )
    # CEE plunge: a few steps with big log_sep drops while dm1r > 0
    seps = [log_sep0, log_sep0 - 0.2, log_sep0 - 0.45, log_sep0 - 0.68, log_sep0 - 0.83]
    masses = [4.9, 4.1, 2.6, 1.35, 0.92]
    for k, (sep, mass) in enumerate(zip(seps, masses, strict=True)):
        b.add(
            age_yr=tms + t_rgb + (k + 1) * 900.0,
            log_t1=3.62 + 0.05 * k,
            log_l1=ll + 1.1 + 0.10 * k,
            m1=mass,
            he_core=0.75,
            x_surf=0.68 - 0.10 * k,
            dm1r=2e-4,
            m2=m2, log_sep=sep,
            log_t2=4.05, log_l2=1.55, log_r2=0.28,
        )
    # emerges as a hot subdwarf
    for f in np.linspace(0.0, 1.0, 60):
        b.add(
            age_yr=tms + t_rgb + 5000.0 + f * 4e6,
            log_t1=3.9 + (4.52 - 3.9) * f**0.5,
            log_l1=1.55 - 0.15 * f,
            m1=0.88,
            he_core=0.72,
            co_core=0.25 * f,
            x_surf=0.15,
            y_surf=0.82,
            m2=m2, log_sep=seps[-1] + 0.02 * f,
            log_t2=4.05, log_l2=1.55, log_r2=0.28,
        )
    return b.build()


def toy_secondary() -> TrackData:
    """11 Msun + 1.4 Msun remnant (post-SN): giant-branch RLOF onto the compact object."""
    b = _TrackBuilder()
    m1, mrem = 11.0, 1.4
    tms = _t_ms(m1)
    log_sep0 = _kepler_log_sep(m1 + mrem, 10.0**1.5)
    _ms_segment(b, m1, tms, n=120, m2=mrem, log_sep=log_sep0)
    lt, ll = _zams(m1)[0] - 0.05, _zams(m1)[1] + 0.28
    t_g = 0.06 * tms
    for f in np.linspace(0.0, 1.0, 70):
        rlof = 4e-6 * np.clip((f - 0.55) / 0.45, 0.0, 1.0)
        b.add(
            age_yr=tms + f * t_g,
            log_t1=lt + (3.58 - lt) * f**0.8,
            log_l1=ll + 0.55 * f,
            m1=m1 * 0.98 - 2.6 * np.clip((f - 0.55) / 0.45, 0.0, 1.0),
            he_core=1.3 * (0.5 + 0.5 * f),
            dm1r=rlof,
            dm2a=0.3 * rlof,
            m2=mrem,
            log_sep=log_sep0 - 0.3 * np.clip((f - 0.55) / 0.45, 0.0, 1.0),
        )
    return b.build()


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------

_DEMO_POPULATIONS: list[dict] = (
    [
        {"imf": "imf135_300", "z": z, "opt": opt, "alpha": None, "hardness": 1.0}
        for z in ("zem4", "z002", "z020")
        for opt in ("bin", "sin")
    ]
    + [{"imf": "imf_chab300", "z": "z020", "opt": "bin", "alpha": None, "hardness": 0.93}]
    + [
        {"imf": "imf135_300", "z": "z020", "opt": "bin", "alpha": a, "hardness": 1.0}
        for a in ("a-02", "a+00", "a+02", "a+04", "a+06")
    ]
)

_DEMO_TRACKS: list[tuple[str, TrackData | None, dict]] = []  # built lazily


def _demo_track_specs() -> list[tuple[ModelName, TrackData, dict]]:
    specs: list[tuple[ModelName, TrackData, dict]] = []
    for mass in (1.0, 15.0, 60.0):
        specs.append(
            (
                ModelName(kind="single", z_label="z020", m1=mass, raw=f"demo-sneplot-z020-{mass:g}"),
                toy_single(mass),
                {
                    "curated": True,
                    "title": f"{mass:g} Msun single star (demo)",
                    "description": "Synthetic toy track — illustrative shapes only.",
                },
            )
        )
    specs.append(
        (
            ModelName(kind="single", z_label="z002", m1=15.0, raw="demo-sneplot-z002-15"),
            toy_single(15.0),
            {"curated": True, "title": "15 Msun single star, low Z (demo)",
             "description": "Synthetic toy track — illustrative shapes only."},
        )
    )
    specs.append(
        (
            ModelName(kind="primary", z_label="z020", m1=15.0, q=0.6, logp=0.6,
                      raw="demo-sneplot-z020-15-0.6-0.6"),
            toy_close_binary(),
            {"curated": True, "title": "15+9 Msun close binary — envelope stripping (demo)",
             "description": "Synthetic toy track: Roche-lobe overflow strips the primary to a hot helium star."},
        )
    )
    specs.append(
        (
            ModelName(kind="primary", z_label="z020", m1=15.0, q=0.6, logp=3.0,
                      raw="demo-sneplot-z020-15-0.6-3.0"),
            toy_wide_binary(),
            {"curated": True, "title": "15+9 Msun wide binary — barely interacts (demo)",
             "description": "Synthetic toy track: same masses as the close system, but too wide to interact."},
        )
    )
    specs.append(
        (
            ModelName(kind="primary", z_label="z020", m1=5.0, q=0.5, logp=0.4,
                      raw="demo-sneplot-z020-5-0.5-0.4"),
            toy_cee_binary(),
            {"curated": True, "title": "5+2.5 Msun binary — common envelope (demo)",
             "description": "Synthetic toy track: unstable mass transfer on the giant branch drives a common-envelope in-spiral."},
        )
    )
    specs.append(
        (
            ModelName(kind="secondary", z_label="z020", m1=11.0, mrem=1.4, logp=1.5,
                      raw="demo-sneplot_2-z020-11-1.4-1.5"),
            toy_secondary(),
            {"curated": True, "title": "11 Msun + compact remnant (demo)",
             "description": "Synthetic toy track: the former secondary evolves and transfers mass onto the 1.4 Msun remnant."},
        )
    )
    return specs


def _seed_populations(session: Session, console: Console) -> None:
    release = session.scalar(select(m.Release).where(m.Release.version == RELEASE_VERSION))
    if release is None:
        release = m.Release(
            version=RELEASE_VERSION,
            name="Synthetic demo (not BPASS)",
            citation="No citation — synthetic demonstration data generated by bib.",
            url=None,
            notes="Toy dataset for exploring the interface. Not for science.",
        )
        session.add(release)
        session.flush()

    wl = _wavelength_grid()
    native_grid = _get_or_create_grid(session, wl, "native", "demo-native")
    edges = sedlib.make_display_edges(wl)
    display_wl, _ = sedlib.rebin_flux(wl, np.ones_like(wl), edges)
    display_grid = _get_or_create_grid(session, display_wl, "display", "demo-display")

    for spec in _DEMO_POPULATIONS:
        z_value = Z_VALUES[spec["z"]]
        alpha = spec["alpha"]
        population = m.Population(
            release_id=release.id,
            imf=spec["imf"],
            z_label=spec["z"],
            z_value=z_value,
            pop_type=spec["opt"],
            alpha_label=alpha,
            alpha_value=ALPHA_VALUES.get(alpha) if alpha else None,
            native_grid_id=native_grid.id,
            display_grid_id=display_grid.id,
            source_file="synthetic://demo-seed",
            sha256=None,
            is_synthetic=True,
            extra={"products": ["spectra", "colours", "ionizing", "starmass",
                                "supernova", "yields", "mlratio"]},
        )
        session.add(population)
        session.flush()

        seds = np.zeros((51, wl.size))
        rows = []
        for i, la in enumerate(sedlib.BPASS_LOG_AGES):
            flux = synth_sed(
                wl, float(la), z_value, binary=spec["opt"] == "bin",
                alpha=ALPHA_VALUES.get(alpha, 0.0) if alpha else 0.0,
                imf_hardness=spec["hardness"],
            )
            seds[i] = flux
            _, flux_ds = sedlib.rebin_flux(wl, flux, edges)
            rows.append(
                {
                    "population_id": population.id,
                    "age_index": i,
                    "log_age": float(la),
                    "n_points": int(flux.size),
                    "flux": sedlib.encode_f32(flux),
                    "n_points_ds": int(flux_ds.size),
                    "flux_ds": sedlib.encode_f32(flux_ds),
                    "log_lbol": float(np.log10(sedlib.integrate_lbol(wl, flux))),
                }
            )
        session.execute(insert(m.Sed), rows)

        tables = _derived_tables(wl, seds, binary=spec["opt"] == "bin")
        for product, table in tables.items():
            _insert_product_rows(session, population.id, product, table)

        # HRD backdrops for the fiducial binary populations
        if spec["imf"] == "imf135_300" and spec["opt"] == "bin" and alpha is None:
            hrd_rows = []
            for i, la in enumerate(sedlib.BPASS_LOG_AGES):
                grids = synth_hrd_grids(float(la), binary=True)
                for h_class in range(3):
                    hrd_rows.append(
                        {
                            "population_id": population.id,
                            "age_index": i,
                            "log_age": float(la),
                            "diagram": "TL",
                            "h_class": h_class,
                            "grid": sedlib.encode_f32(grids[h_class]),
                        }
                    )
            for start in range(0, len(hrd_rows), 64):
                session.execute(insert(m.HrdGrid), hrd_rows[start : start + 64])

        tag = f"{spec['imf']}/{spec['opt']}/{spec['z']}" + (f"/{alpha}" if alpha else "")
        console.print(f"  population {tag} [green]seeded[/green]")


def _seed_models(session: Session, console: Console) -> None:
    for name, track, spec in _demo_track_specs():
        _insert_model(
            session, name, track,
            source_file="synthetic://demo-seed", sha256=None, spec=spec, is_synthetic=True,
        )
        console.print(f"  model {name.raw} [green]seeded[/green] ({track.n_steps} steps)")


def seed_demo(force: bool = False, console: Console | None = None) -> None:
    console = console or Console()
    from bib.db.bootstrap import init_database

    init_database(console=console)

    with session_scope() as session:
        existing = session.scalar(
            select(m.Population.id).where(m.Population.is_synthetic).limit(1)
        )
        if existing is not None:
            if not force:
                console.print("[yellow]demo data already present — use --force to reseed[/yellow]")
                return
            console.print("removing existing synthetic data...")
            session.execute(
                delete(m.Population).where(m.Population.is_synthetic)
            )
            session.execute(delete(m.StellarModel).where(m.StellarModel.is_synthetic))
            session.execute(delete(m.Release).where(m.Release.version == RELEASE_VERSION))

        console.print("[bold]seeding synthetic demo dataset[/bold] (not for science)")
        _seed_populations(session, console)
        _seed_models(session, console)

    from bib.web.templating import invalidate_synthetic_cache

    invalidate_synthetic_cache()
    console.print("[green]demo seed complete[/green]")
