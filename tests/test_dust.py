"""Dust law behaviour: identity at E(B-V)=0, known values, range clamping."""

from __future__ import annotations

import numpy as np
import pytest

from bib.science.dust import DUST_LAWS, _calzetti00_alav, apply_dust


def test_zero_ebv_is_identity():
    wl = np.linspace(1000, 50000, 100)
    flux = np.random.default_rng(1).uniform(0.5, 2.0, wl.size)
    result = apply_dust(wl, flux, "ccm89", ebv=0.0)
    np.testing.assert_array_equal(result.flux, flux)
    assert result.a_v == 0.0


def test_ccm89_v_band_normalisation():
    """A(V)/A_V = 1 by construction: at ~5500 Å the dimming is 10^(-0.4 Rv Ebv)."""
    wl = np.array([5495.0])
    flux = np.array([1.0])
    ebv, rv = 0.1, 3.1
    result = apply_dust(wl, flux, "ccm89", ebv=ebv, rv=rv)
    expected = 10.0 ** (-0.4 * rv * ebv)
    assert result.flux[0] == pytest.approx(expected, rel=0.02)
    assert result.a_v == pytest.approx(rv * ebv)


def test_calzetti00_v_band_value():
    """Calzetti k(0.55 µm) ≈ R_V, i.e. A(V)/A_V ≈ 1 (published polynomial)."""
    alav = _calzetti00_alav(np.array([1.0 / 0.55]), rv=4.05)
    assert alav[0] == pytest.approx(1.0, abs=0.01)


def test_calzetti00_published_uv_value():
    """k(0.15 µm) from the published polynomial, computed independently."""
    lam = 0.15
    x = 1.0 / lam
    k = 2.659 * (-2.156 + 1.509 * x - 0.198 * x**2 + 0.011 * x**3) + 4.05
    alav = _calzetti00_alav(np.array([x]), rv=4.05)
    assert alav[0] == pytest.approx(k / 4.05, rel=1e-12)
    assert k == pytest.approx(10.33, abs=0.05)  # sanity: matches the literature


def test_uv_extinction_exceeds_optical():
    wl = np.array([1500.0, 5500.0])
    flux = np.array([1.0, 1.0])
    for law in DUST_LAWS:
        result = apply_dust(wl, flux, law, ebv=0.2)
        assert result.flux[0] < result.flux[1], f"{law}: UV should be dimmed more than V"


def test_out_of_range_wavelengths_clamped():
    """Far outside every law's window the factor is finite and equals the boundary."""
    wl = np.array([10.0, 5.0e6])  # X-ray-ish and far-IR
    flux = np.array([1.0, 1.0])
    for law_key, law in DUST_LAWS.items():
        result = apply_dust(wl, flux, law_key, ebv=0.3)
        assert np.all(np.isfinite(result.flux))
        assert np.all(result.flux > 0)
        lo_a, hi_a = law.wavelength_range_a
        boundary = apply_dust(np.array([lo_a * 1.0001, hi_a * 0.9999]), flux, law_key, ebv=0.3)
        np.testing.assert_allclose(result.flux, boundary.flux, rtol=5e-3)


def test_fixed_rv_laws_ignore_user_rv():
    wl = np.array([5500.0])
    flux = np.array([1.0])
    a = apply_dust(wl, flux, "smc", ebv=0.1, rv=5.0)
    assert a.rv == DUST_LAWS["smc"].fixed_rv


def test_unknown_law_raises():
    with pytest.raises(KeyError):
        apply_dust(np.array([5500.0]), np.array([1.0]), "nosuchlaw", ebv=0.1)
