"""Parser tests against synthetic fixture files with the documented shapes."""

from __future__ import annotations

import gzip

import numpy as np
import pytest

from bib.ingest import parsers
from bib.science.sed import BPASS_LOG_AGES

RNG = np.random.default_rng(42)


def write(path, array, gz=False):
    text_bytes = b""
    import io

    buf = io.BytesIO()
    np.savetxt(buf, array)
    text_bytes = buf.getvalue()
    if gz:
        path.write_bytes(gzip.compress(text_bytes))
    else:
        path.write_bytes(text_bytes)
    return path


# --- spectra -------------------------------------------------------------------


def spectra_array(n_wl=150):
    wl = np.linspace(1.0, 100000.0, n_wl)
    flux = RNG.uniform(0.0, 2.0, size=(n_wl, 51))
    return np.column_stack([wl, flux])


def test_parse_spectra(tmp_path):
    path = write(tmp_path / "spectra-bin-imf135_300.z020.dat", spectra_array())
    data = parsers.parse_spectra(path)
    assert data.wavelength.shape == (150,)
    assert data.flux.shape == (51, 150)
    assert data.n_negative_clamped == 0


def test_parse_spectra_gzipped(tmp_path):
    path = write(tmp_path / "spectra-bin-imf135_300.z020.dat.gz", spectra_array(), gz=True)
    data = parsers.parse_spectra(path)
    assert data.flux.shape == (51, 150)


def test_parse_spectra_clamps_negative_fluxes(tmp_path):
    arr = spectra_array()
    arr[10, 5] = -1.0  # the v2.2.0 white-dwarf bug this subrelease fixed
    path = write(tmp_path / "spectra.dat", arr)
    data = parsers.parse_spectra(path)
    assert data.n_negative_clamped == 1
    assert np.all(data.flux >= 0)


def test_parse_spectra_wrong_columns(tmp_path):
    arr = spectra_array()[:, :30]
    path = write(tmp_path / "spectra.dat", arr)
    with pytest.raises(parsers.ParseError, match="columns"):
        parsers.parse_spectra(path)


def test_parse_spectra_unsorted_wavelength(tmp_path):
    arr = spectra_array()
    arr[0, 0], arr[1, 0] = arr[1, 0], arr[0, 0]
    path = write(tmp_path / "spectra.dat", arr)
    with pytest.raises(parsers.ParseError, match="increasing"):
        parsers.parse_spectra(path)


# --- per-age product tables ------------------------------------------------------


def aged_table(n_cols):
    data = RNG.uniform(-1.0, 1.0, size=(51, n_cols))
    data[:, 0] = BPASS_LOG_AGES
    return data


def test_parse_colours(tmp_path):
    path = write(tmp_path / "colours.dat", aged_table(22))
    assert parsers.parse_colours(path).shape == (51, 22)


def test_parse_colours_ignores_trailing_columns(tmp_path):
    table = aged_table(26)
    table[:, 22:] = 99.0
    path = write(tmp_path / "colours.dat", table)
    parsed = parsers.parse_colours(path)
    assert parsed.shape == (51, 22)
    assert not np.any(parsed[:, 1:] == 99.0)


def test_parse_colours_bad_age_column(tmp_path):
    data = aged_table(22)
    data[:, 0] += 0.5
    path = write(tmp_path / "colours.dat", data)
    with pytest.raises(parsers.ParseError, match="age column"):
        parsers.parse_colours(path)


def test_parse_ionizing(tmp_path):
    path = write(tmp_path / "ionizing.dat", aged_table(5))
    assert parsers.parse_ionizing(path).shape == (51, 5)


def test_parse_starmass_single_and_binary(tmp_path):
    assert parsers.parse_starmass(write(tmp_path / "s2.dat", aged_table(2))).shape == (51, 2)
    assert parsers.parse_starmass(write(tmp_path / "s3.dat", aged_table(3))).shape == (51, 3)
    with pytest.raises(parsers.ParseError):
        parsers.parse_starmass(write(tmp_path / "s4.dat", aged_table(4)))


def test_parse_supernova_yields_mlratio(tmp_path):
    assert parsers.parse_supernova(write(tmp_path / "sn.dat", aged_table(18))).shape == (51, 18)
    assert parsers.parse_yields(write(tmp_path / "y.dat", aged_table(9))).shape == (51, 9)
    assert parsers.parse_mlratio(write(tmp_path / "ml.dat", aged_table(3))).shape == (51, 3)


def test_parse_star_counts(tmp_path):
    path = write(tmp_path / "numbers.dat", aged_table(21))
    assert parsers.parse_star_counts(path).shape == (51, 21)


def test_parse_mlratio_skips_text_header(tmp_path):
    path = tmp_path / "mlratio.dat"
    body = write(tmp_path / "_ml_body.dat", aged_table(3)).read_bytes()
    path.write_bytes(b"    log(age) M/L(K band) M/L(V band)\n" + body)
    assert parsers.parse_mlratio(path).shape == (51, 3)
