"""Unit tests for SED array handling (codec, display rebinning, scaling)."""

from __future__ import annotations

import numpy as np
import pytest

from bib.science import sed as sedlib


def test_f32_roundtrip():
    values = np.array([0.0, 1.5, 3.25e-30, 8.1e30])
    out = sedlib.decode_f32(sedlib.encode_f32(values), n_points=4)
    assert out.dtype == np.float64
    np.testing.assert_allclose(out, values, rtol=1e-7)


def test_f64_roundtrip_exact():
    values = np.linspace(1.0, 1e5, 1000)
    out = sedlib.decode_f64(sedlib.encode_f64(values), n_points=1000)
    np.testing.assert_array_equal(out, values)


def test_decode_length_check():
    buf = sedlib.encode_f32(np.arange(10.0))
    with pytest.raises(ValueError, match="expected 5"):
        sedlib.decode_f32(buf, n_points=5)


def test_bpass_age_grid():
    assert sedlib.BPASS_LOG_AGES.size == 51
    assert sedlib.BPASS_LOG_AGES[0] == 6.0
    assert sedlib.BPASS_LOG_AGES[-1] == 11.0


def test_display_edges_linear_grid():
    """The BPASS-like 1 Å linear grid: native kept in the far UV, log bins above."""
    wl = np.arange(1.0, 100001.0)  # 1 Å steps, like the real release
    edges = sedlib.make_display_edges(wl, target_points=4000)
    n_bins = edges.size - 1
    assert 2000 < n_bins < 8000  # dramatically fewer than 100k, near target
    # Below the crossover the native 1 Å sampling must be preserved.
    d = np.diff(edges)
    assert np.all(d[:50] <= 1.0 + 1e-9)


def test_display_edges_log_native_grid():
    """A log-spaced native grid coarser than the target must be kept whole."""
    wl = np.logspace(0, 5, 2000)
    edges = sedlib.make_display_edges(wl, target_points=4000)
    assert edges.size - 1 <= 2001  # nothing upsampled


def test_rebin_preserves_constant_flux_density():
    wl = np.arange(1.0, 10001.0)
    flux = np.full(wl.size, 7.5)
    edges = sedlib.make_display_edges(wl, target_points=500)
    centres, binned = sedlib.rebin_flux(wl, flux, edges)
    assert centres.size == edges.size - 1
    np.testing.assert_allclose(binned, 7.5, rtol=1e-12)


def test_rebin_fills_empty_bins_by_interpolation():
    wl = np.array([1.0, 2.0, 3.0, 100.0, 101.0, 102.0])
    flux = np.array([1.0, 1.0, 1.0, 3.0, 3.0, 3.0])
    edges = np.array([0.5, 3.5, 50.0, 99.0, 102.5])  # second+third bins are empty-ish
    _, binned = sedlib.rebin_flux(wl, flux, edges)
    assert np.all(np.isfinite(binned))
    assert binned[0] == pytest.approx(1.0)
    assert binned[-1] == pytest.approx(3.0)


def test_scale_by_mass_is_linear():
    flux = np.array([1.0, 2.0])
    np.testing.assert_allclose(sedlib.scale_by_mass(flux, 2e6), [2.0, 4.0])
    np.testing.assert_allclose(sedlib.scale_by_mass(flux, 1e6), flux)


def test_integrate_lbol_triangle():
    # Triangle of height 2 over width 100 -> area 100.
    wl = np.array([0.0, 50.0, 100.0])
    flux = np.array([0.0, 2.0, 0.0])
    assert sedlib.integrate_lbol(wl, flux) == pytest.approx(100.0)


def test_flux_at_10pc_scaling():
    """1 L_sun/Å at 10 pc: L_sun_erg_s / (4 pi (10 pc)^2)."""
    expected = sedlib.L_SUN_ERG_S / sedlib.TEN_PC_AREA_CM2
    out = sedlib.flux_at_10pc(np.array([1.0]))
    assert out[0] == pytest.approx(expected, rel=1e-12)
