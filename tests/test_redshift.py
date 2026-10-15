"""Observer-frame (redshift) transformation of SEDs."""

from __future__ import annotations

import numpy as np
import pytest

from bib.science.photometry import AB_ZERO_FNU, C_A_S, FilterCurve, ab_magnitude
from bib.science.redshift import (
    luminosity_distance_cm,
    luminosity_distance_mpc,
    observe,
    plot_level_lsun_a,
)
from bib.science.sed import L_SUN_ERG_S, PC_CM


def box_filter(lo: float = 5000.0, hi: float = 6000.0) -> FilterCurve:
    wl = np.linspace(lo, hi, 200)
    return FilterCurve(
        name="box",
        display_name="box",
        group="test",
        detector_type="photon",
        wavelength=wl,
        transmission=np.ones_like(wl),
    )


def test_z_zero_is_ten_parsecs():
    assert luminosity_distance_cm(0.0) == pytest.approx(10.0 * PC_CM)
    assert luminosity_distance_mpc(0.0) is None


def test_luminosity_distance_matches_published_value():
    """Flat ΛCDM H0=70 Ωm=0.3 gives D_L(z=1) ≈ 6607 Mpc."""
    assert luminosity_distance_mpc(1.0) == pytest.approx(6607.0, rel=0.01)


def test_wavelengths_stretch_by_one_plus_z():
    wl = np.linspace(1000.0, 10000.0, 50)
    flux = np.ones_like(wl)
    wl_obs, _ = observe(wl, flux, 2.5)
    np.testing.assert_allclose(wl_obs, wl * 3.5)


def test_bolometric_flux_is_l_over_4pi_dl2():
    """D_L absorbs every redshift factor: ∫f_λ dλ_obs = L_bol / (4π D_L²)."""
    wl = np.linspace(100.0, 90000.0, 4000)
    flux = np.exp(-(((wl - 3000.0) / 2000.0) ** 2))  # arbitrary smooth SED, L_sun/Å
    l_bol = np.trapezoid(flux, wl) * L_SUN_ERG_S

    z = 1.7
    wl_obs, f_lam = observe(wl, flux, z)
    f_bol = np.trapezoid(f_lam, wl_obs)
    expected = l_bol / (4.0 * np.pi * luminosity_distance_cm(z) ** 2)
    assert f_bol == pytest.approx(expected, rel=1e-10)


def test_flat_lnu_source_apparent_magnitude_analytic():
    """For L_ν = const: m(z) = M + 5log10(D_L/10pc) − 2.5log10(1+z), any filter."""
    wl = np.geomspace(300.0, 60000.0, 6000)
    flux_lsun_a = (5500.0 / wl) ** 2  # L_λ ∝ λ⁻² ⇔ flat L_ν
    filt = box_filter()

    m_abs = ab_magnitude(wl, flux_lsun_a, filt).ab_mag

    z = 3.0
    wl_obs, f_lam = observe(wl, flux_lsun_a, z)
    m_app = ab_magnitude(wl_obs, f_lam, filt, flux_unit="flam_cgs").ab_mag

    d_l = luminosity_distance_cm(z)
    mu = 5.0 * np.log10(d_l / (10.0 * PC_CM))
    assert m_app == pytest.approx(m_abs + mu - 2.5 * np.log10(1.0 + z), abs=1e-6)


def test_plot_level_sits_on_plotted_curve():
    """Marker level from m_AB lands on the L_λ,rest/(1+z) curve for a flat SED."""
    wl = np.geomspace(300.0, 60000.0, 6000)
    flux = np.full_like(wl, 2.0)  # flat L_λ: pivot conversion is exact
    z = 1.2
    wl_obs, f_lam = observe(wl, flux, z)
    result = ab_magnitude(wl_obs, f_lam, box_filter(), flux_unit="flam_cgs")

    f_nu = AB_ZERO_FNU * 10.0 ** (-0.4 * result.ab_mag)
    f_lam_pivot = f_nu * C_A_S / result.lambda_eff**2
    level = plot_level_lsun_a(f_lam_pivot, z)
    # lambda_eff is not exactly the pivot wavelength; agreement to ~0.1% is
    # far below anything visible on the plot.
    assert level == pytest.approx(2.0 / (1.0 + z), rel=1e-3)


def test_z_zero_observe_matches_ten_pc_absolute_frame():
    """At z=0 the cgs path reproduces the classic absolute AB magnitude."""
    wl = np.geomspace(300.0, 60000.0, 6000)
    flux = 3.0 * (wl / 5500.0) ** -1.5
    filt = box_filter()
    classic = ab_magnitude(wl, flux, filt).ab_mag
    wl_obs, f_lam = observe(wl, flux, 0.0)
    via_cgs = ab_magnitude(wl_obs, f_lam, filt, flux_unit="flam_cgs").ab_mag
    assert via_cgs == pytest.approx(classic, abs=1e-9)
