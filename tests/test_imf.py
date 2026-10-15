"""BPASS IMF code parsing and ξ(log M) shapes."""

from __future__ import annotations

import numpy as np
import pytest

from bib.science.imf import describe_imf


@pytest.mark.parametrize(
    "code, form, form_label, alpha, m_max",
    [
        ("imf_chab100", "chabrier", "Chabrier", 1.35, 100.0),
        ("imf135_100", "broken_powerlaw", "Broken power-law", 1.35, 100.0),
        ("imf100_300", "broken_powerlaw", "Broken power-law", 1.00, 300.0),
        ("imf170_300", "broken_powerlaw", "Broken power-law", 1.70, 300.0),
        ("imf135all_100", "powerlaw", "Power-law", 1.35, 100.0),
    ],
)
def test_describe_known_imfs(code, form, form_label, alpha, m_max):
    info = describe_imf(code)
    assert info.form == form
    assert info.form_label == form_label
    assert info.alpha == pytest.approx(alpha)
    assert info.m_max == pytest.approx(m_max)
    assert "α=" in info.label
    assert form_label in info.label
    assert info.params_label.startswith(f"{alpha:g}")


def test_unknown_imf_keeps_raw_code():
    info = describe_imf("imf_custom")
    assert info.form == "unknown"
    assert info.label == "imf_custom"
    assert info.params_label == "—"


def test_xi_normalised_at_one_msun():
    for code in ("imf_chab100", "imf135_100", "imf135all_100"):
        xi = describe_imf(code).xi(np.array([1.0]))
        assert xi[0] == pytest.approx(1.0)


def test_dndm_is_xi_over_m_ln10():
    info = describe_imf("imf135_100")
    payload = info.to_public_dict(curve=True)
    mass = np.array(payload["mass"])
    xi = np.array(payload["xi"])
    dndm = np.array(payload["dndm"])
    assert dndm == pytest.approx(xi / (mass * np.log(10.0)))


def test_chabrier_turns_over_below_solar():
    info = describe_imf("imf_chab100")
    broken = describe_imf("imf135_100")
    m = np.array([0.2])
    assert info.xi(m)[0] < broken.xi(m)[0]


def test_steeper_alpha_has_fewer_massive_stars():
    flat = describe_imf("imf100_300").xi(np.array([30.0]))[0]
    steep = describe_imf("imf170_300").xi(np.array([30.0]))[0]
    assert steep < flat
