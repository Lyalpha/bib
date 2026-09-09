"""Analytic checks of the AB photometry engine.

The key invariant: a source whose f_nu is exactly 3631 Jy at 10 pc has
m_AB = 0 in *every* filter, for both photon- and energy-counting detectors.
"""

from __future__ import annotations

import numpy as np
import pytest

from bib.science.photometry import (
    AB_ZERO_FNU,
    C_A_S,
    FilterCurve,
    ab_magnitude,
    parse_custom_filter,
    pivot_wavelength,
)
from bib.science.sed import L_SUN_ERG_S, TEN_PC_AREA_CM2


def ab_flat_sed(wl: np.ndarray) -> np.ndarray:
    """SED in L_sun/Å whose f_nu at 10 pc is exactly 3631 Jy at all wavelengths."""
    f_lambda_10pc = AB_ZERO_FNU * C_A_S / wl**2  # erg/s/cm^2/Å
    return f_lambda_10pc * TEN_PC_AREA_CM2 / L_SUN_ERG_S


def box_filter(lo: float, hi: float, n: int = 200, detector: str = "photon") -> FilterCurve:
    wl = np.linspace(lo, hi, n)
    return FilterCurve(
        name="box", display_name="box", wavelength=wl,
        transmission=np.ones(n), detector_type=detector,
    )


@pytest.mark.parametrize("detector", ["photon", "energy"])
def test_ab_flat_source_is_zero_mag(detector):
    wl = np.linspace(1000.0, 11000.0, 5000)
    sed = ab_flat_sed(wl)
    result = ab_magnitude(wl, sed, box_filter(4000.0, 6000.0, detector=detector))
    assert result.ab_mag == pytest.approx(0.0, abs=1e-9)
    assert result.coverage == pytest.approx(1.0)


def test_flux_scaling_shifts_magnitude():
    """x100 flux -> exactly -5 magnitudes."""
    wl = np.linspace(1000.0, 11000.0, 5000)
    sed = ab_flat_sed(wl)
    filt = box_filter(4000.0, 6000.0)
    m1 = ab_magnitude(wl, sed, filt).ab_mag
    m2 = ab_magnitude(wl, sed * 100.0, filt).ab_mag
    assert m2 - m1 == pytest.approx(-5.0, abs=1e-10)


def test_pivot_wavelength_of_box_filter():
    lo, hi = 4000.0, 6000.0
    wl = np.linspace(lo, hi, 20000)
    pivot = pivot_wavelength(wl, np.ones(wl.size))
    expected = np.sqrt(((hi**2 - lo**2) / 2.0) / np.log(hi / lo))
    assert pivot == pytest.approx(expected, abs=0.5)


def test_no_overlap_returns_none():
    wl = np.linspace(4000.0, 6000.0, 500)
    result = ab_magnitude(wl, ab_flat_sed(wl), box_filter(20000.0, 30000.0))
    assert result.ab_mag is None
    assert result.coverage == 0.0


def test_partial_coverage_reported():
    wl = np.linspace(5000.0, 9000.0, 2000)  # SED starts inside the filter
    result = ab_magnitude(wl, ab_flat_sed(wl), box_filter(4000.0, 6000.0))
    assert result.ab_mag is not None
    assert 0.4 < result.coverage < 0.6


def test_coarse_sed_evaluated_on_filter_grid():
    """SED coarser than the filter: engine falls back to the filter's grid."""
    wl = np.linspace(1000.0, 11000.0, 8)  # absurdly coarse
    result = ab_magnitude(wl, ab_flat_sed(wl), box_filter(4000.0, 6000.0))
    # Linear interpolation of a smooth curve: near zero, not exactly.
    assert result.ab_mag == pytest.approx(0.0, abs=0.05)


def test_filter_curve_sorts_and_clips():
    curve = FilterCurve(
        name="messy", display_name="messy",
        wavelength=np.array([6000.0, 4000.0, 5000.0, 4500.0]),
        transmission=np.array([0.5, -0.1, 1.0, 0.7]),
    )
    assert np.all(np.diff(curve.wavelength) > 0)
    assert np.all(curve.transmission >= 0)
    assert curve.lambda_eff > 0


def test_filter_curve_rejects_zero_transmission():
    with pytest.raises(ValueError, match="identically zero"):
        FilterCurve(
            name="dead", display_name="dead",
            wavelength=np.linspace(4000, 5000, 10),
            transmission=np.zeros(10),
        )


# --- custom filter parsing ---------------------------------------------------


def test_parse_custom_filter_whitespace_and_comments():
    text = "# my filter\n4000 0.1\n4500 0.9\n5000 1.0\n5500 0.4\n"
    curve = parse_custom_filter(text, name="up")
    assert curve.wavelength.size == 4
    assert curve.detector_type == "photon"


def test_parse_custom_filter_csv_with_header():
    text = "wavelength,transmission\n4000,0.1\n4500,0.9\n5000,1.0\n5500,0.4\n"
    curve = parse_custom_filter(text)
    assert curve.wavelength[0] == 4000.0


def test_parse_custom_filter_too_few_rows():
    with pytest.raises(ValueError, match="at least 4"):
        parse_custom_filter("4000 1\n5000 1\n6000 1\n")


def test_parse_custom_filter_rejects_microns():
    text = "0.4 0.5\n0.5 1.0\n0.6 0.8\n0.7 0.2\n"
    with pytest.raises(ValueError, match="Ångströms"):
        parse_custom_filter(text)


def test_parse_custom_filter_rejects_bad_line():
    text = "4000 0.1\n4500 abc\n5000 1.0\n5500 0.4\n"
    with pytest.raises(ValueError, match="line 2"):
        parse_custom_filter(text)
