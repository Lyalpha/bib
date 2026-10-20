"""IGM transmission: limits, monotonicity, and agreement with reference implementations."""

from __future__ import annotations

import numpy as np
import pytest

from bib.science.igm import (
    IGM_MODELS,
    LYMAN_ALPHA_A,
    apply_igm,
    igm_info,
    igm_transmission,
)

# Reference values computed with eazy-py's ``Inoue14.full_IGM`` (which loads the
# published Table 2 coefficients from its own data files) for (z, λ_rest/Å).
_EAZY_REFERENCE = [
    (2.5, 1210.0, 0.786094),
    (2.5, 950.0, 0.833143),
    (2.5, 850.0, 0.501005),
    (3.5, 1210.0, 0.543900),
    (3.5, 950.0, 0.631059),
    (3.5, 850.0, 0.194141),
    (5.5, 1210.0, 0.051152),
    (5.5, 900.0, 0.025593),
    (1.0, 1100.0, 0.965643),
    (1.0, 700.0, 0.696711),
]


@pytest.mark.parametrize("model", sorted(IGM_MODELS))
def test_zero_or_negative_redshift_is_identity(model):
    wl = np.linspace(100.0, 50000.0, 500)
    np.testing.assert_array_equal(igm_transmission(wl, 0.0, model), 1.0)
    np.testing.assert_array_equal(igm_transmission(wl, -0.1, model), 1.0)


@pytest.mark.parametrize("model", sorted(IGM_MODELS))
def test_transmission_is_one_redward_of_lyman_alpha(model):
    z = 4.0
    wl = np.linspace(LYMAN_ALPHA_A * (1 + z) + 1.0, 60000.0, 300)
    np.testing.assert_array_equal(igm_transmission(wl, z, model), 1.0)


@pytest.mark.parametrize("model", sorted(IGM_MODELS))
def test_transmission_bounded_and_finite(model):
    for z in (0.3, 1.5, 3.0, 6.0, 12.0, 20.0):
        wl = np.arange(100.0, 30000.0, 2.0)
        t = igm_transmission(wl, z, model)
        assert np.all(np.isfinite(t))
        assert np.all(t >= 0.0) and np.all(t <= 1.0)


@pytest.mark.parametrize("model", sorted(IGM_MODELS))
def test_transmission_decreases_with_redshift_at_fixed_rest_wavelength(model):
    rest = np.array([1000.0, 1150.0])
    previous = None
    for z in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
        t = igm_transmission(rest * (1 + z), z, model)
        if previous is not None:
            assert np.all(t <= previous + 1e-12)
        previous = t


def test_lyman_continuum_is_more_opaque_than_forest():
    z = 3.0
    rest = np.array([1150.0, 800.0])
    for model in IGM_MODELS:
        t = igm_transmission(rest * (1 + z), z, model)
        assert t[1] < t[0]


@pytest.mark.parametrize(("z", "rest", "expected"), _EAZY_REFERENCE)
def test_inoue14_matches_eazy_reference(z, rest, expected):
    t = igm_transmission(np.array([rest * (1 + z)]), z, "inoue14")
    assert t[0] == pytest.approx(expected, abs=2e-6)


def test_madau95_lyman_alpha_forest_matches_closed_form():
    """Just blueward of Lyα only the first term of eq. 15 contributes."""
    z = 3.0
    rest = 1210.0
    lobs = rest * (1 + z)
    tau = 0.0036 * (lobs / 1215.67) ** 3.46
    t = igm_transmission(np.array([lobs]), z, "madau95")
    assert t[0] == pytest.approx(np.exp(-tau), rel=1e-12)


def test_models_agree_to_within_expected_scatter_in_the_forest():
    """Inoue+14 and Madau95 differ by at most ~0.1 in the forest at z ~ 3."""
    z = 3.0
    rest = np.linspace(1030.0, 1210.0, 50)
    a = igm_transmission(rest * (1 + z), z, "inoue14")
    b = igm_transmission(rest * (1 + z), z, "madau95")
    assert np.max(np.abs(a - b)) < 0.1


def test_apply_igm_and_info():
    z = 2.0
    wl = np.array([2000.0, 3000.0, 5000.0])
    flux = np.array([1.0, 1.0, 1.0])
    out = apply_igm(wl, flux, z, "inoue14")
    assert out[0] < 1.0 and out[1] < 1.0 and out[2] == 1.0
    info = igm_info(z, "inoue14")
    assert info["model"] == "inoue14"
    assert info["label"] == "Inoue et al. (2014)"
    assert info["lyman_alpha_obs_a"] == pytest.approx(LYMAN_ALPHA_A * 3)


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        igm_transmission(np.array([5000.0]), 1.0, "nosuchmodel")
