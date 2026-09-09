"""Track geometry helpers: Roche lobes, mass-loss rates, decimation."""

from __future__ import annotations

import numpy as np
import pytest

from bib.science.tracks import decimate_indices, eggleton_rl_fraction, mass_loss_rate


def test_eggleton_equal_masses():
    """Classic value: q=1 gives R_L/a = 0.49/(0.6 + ln 2) ≈ 0.379."""
    expected = 0.49 / (0.6 + np.log(2.0))
    assert eggleton_rl_fraction(1.0) == pytest.approx(expected, rel=1e-12)
    assert expected == pytest.approx(0.379, abs=1e-3)


def test_eggleton_monotonic_in_q():
    q = np.logspace(-2, 2, 50)
    rl = eggleton_rl_fraction(q)
    assert np.all(np.diff(rl) > 0)  # more massive donor -> larger lobe
    assert np.all((rl > 0) & (rl < 1))


def test_mass_loss_rate_simple_slope():
    """Returns |dM/dt| for losses (documented convention), zero for gains."""
    age = np.linspace(0.0, 1e6, 101)
    mass = 10.0 - 1e-6 * age  # loses 1 Msun per Myr
    mdot = mass_loss_rate(age, mass)
    np.testing.assert_allclose(mdot[1:-1], 1e-6, rtol=1e-6)

    gaining = mass_loss_rate(age, 10.0 + 1e-6 * age)  # accretor: no 'loss'
    np.testing.assert_allclose(gaining, 0.0, atol=1e-15)


def test_mass_loss_rate_survives_repeated_ages():
    """Synthetic tracks may repeat ages at segment joins — no NaN/inf allowed."""
    age = np.array([0.0, 1.0, 1.0, 1.0, 2.0, 3.0]) * 1e6
    mass = np.array([10.0, 9.9, 9.9, 9.8, 9.7, 9.6])
    mdot = mass_loss_rate(age, mass)
    assert np.all(np.isfinite(mdot))


def test_decimate_keeps_endpoints_and_events():
    keep = {123, 456}
    idx = decimate_indices(1000, target=50, keep=keep)
    assert idx[0] == 0
    assert idx[-1] == 999
    assert keep <= set(idx.tolist())
    assert idx.size <= 60  # near target, not wildly above
    assert np.all(np.diff(idx) > 0)


def test_decimate_short_track_untouched():
    idx = decimate_indices(20, target=50)
    np.testing.assert_array_equal(idx, np.arange(20))
