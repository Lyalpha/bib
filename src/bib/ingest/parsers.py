"""Parsers for BPASS v2.2.1 / v2.3 data-release files.

Formats follow the BPASS v2.2 user manual READMEs exactly. All parsers accept
plain-text ``.dat`` files, transparently handling ``.gz`` compression, and
validate shape/sanity before anything reaches the database.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bib.science.sed import BPASS_LOG_AGES

N_AGES = 51

# Metallicity mass-fraction labels used in BPASS filenames.
Z_VALUES: dict[str, float] = {
    "zem5": 1.0e-5,
    "zem4": 1.0e-4,
    "z001": 0.001,
    "z002": 0.002,
    "z003": 0.003,
    "z004": 0.004,
    "z006": 0.006,
    "z008": 0.008,
    "z010": 0.010,
    "z014": 0.014,
    "z020": 0.020,
    "z030": 0.030,
    "z040": 0.040,
}

# v2.3 alpha-enhancement labels: Δ(log(alpha/Fe)) relative to solar.
ALPHA_VALUES: dict[str, float] = {
    "a-02": -0.2,
    "a+00": 0.0,
    "a+02": +0.2,
    "a+04": +0.4,
    "a+06": +0.6,
}


class ParseError(ValueError):
    """A BPASS file did not match its documented format."""


def _open_text(path: Path) -> io.TextIOBase:
    if str(path).endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"))
    return open(path, encoding="ascii", errors="replace")


def _load_table(path: Path, n_cols: int | None = None, n_rows: int | None = None) -> np.ndarray:
    with _open_text(path) as fh:
        lines = fh.read().splitlines()
    start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        token = line.split(None, 1)[0]
        try:
            float(token)
            start = i
        except ValueError:
            start = i + 1
        break
    try:
        data = np.loadtxt(io.StringIO("\n".join(lines[start:])), ndmin=2)
    except ValueError as exc:
        raise ParseError(f"{path.name}: could not parse as numeric table ({exc})") from exc
    if n_cols is not None and data.shape[1] != n_cols:
        raise ParseError(f"{path.name}: expected {n_cols} columns, found {data.shape[1]}")
    if n_rows is not None and data.shape[0] != n_rows:
        raise ParseError(f"{path.name}: expected {n_rows} rows, found {data.shape[0]}")
    return data


def _validate_age_column(path: Path, log_ages: np.ndarray) -> None:
    if not np.allclose(log_ages, BPASS_LOG_AGES, atol=5e-3):
        raise ParseError(f"{path.name}: age column does not match the BPASS 6.0–11.0 grid")


# ---------------------------------------------------------------------------
# Spectral energy distributions
# ---------------------------------------------------------------------------


@dataclass
class SpectraData:
    wavelength: np.ndarray  # (N,) Å
    flux: np.ndarray  # (51, N) L_sun/Å per 1e6 Msun
    n_negative_clamped: int = 0


def parse_spectra(path: Path) -> SpectraData:
    """Parse ``spectra-<opt>-<imf>.<z>.dat``: col 1 wavelength, cols 2–52 ages."""
    data = _load_table(path, n_cols=N_AGES + 1)
    wavelength = data[:, 0]
    if wavelength.size < 100 or np.any(np.diff(wavelength) <= 0):
        raise ParseError(f"{path.name}: wavelength axis not strictly increasing")
    flux = data[:, 1:].T.copy()  # (51, N)
    negatives = int(np.count_nonzero(flux < 0))
    if negatives:
        # v2.2.1 fixed the negative-flux bug; clamp any residuals and report.
        flux[flux < 0] = 0.0
    return SpectraData(wavelength=wavelength, flux=flux, n_negative_clamped=negatives)


# ---------------------------------------------------------------------------
# Per-age population products (51-row tables)
# ---------------------------------------------------------------------------


def parse_colours(path: Path) -> np.ndarray:
    """22 columns: log_age, V-I, U, B, V, R, I, J, H, K, ugriz, WFPC2/ACS bands.

    Official v2.2.1 files append extra filter columns (26 total). Keep the
    documented 22 and ignore the trailing extras.
    """
    data = _load_table(path, n_rows=N_AGES)
    if data.shape[1] < 22:
        raise ParseError(f"{path.name}: expected at least 22 columns, found {data.shape[1]}")
    _validate_age_column(path, data[:, 0])
    return data[:, :22]


def parse_ionizing(path: Path) -> np.ndarray:
    """5 columns: log_age, log Nion, log L_Ha, log L_FUV, log L_NUV."""
    data = _load_table(path, n_cols=5, n_rows=N_AGES)
    _validate_age_column(path, data[:, 0])
    return data


def parse_starmass(path: Path) -> np.ndarray:
    """2 (sin) or 3 (bin) columns: log_age, live mass, [remnant mass]."""
    data = _load_table(path, n_rows=N_AGES)
    if data.shape[1] not in (2, 3):
        raise ParseError(f"{path.name}: expected 2 or 3 columns, found {data.shape[1]}")
    _validate_age_column(path, data[:, 0])
    return data


def parse_supernova(path: Path) -> np.ndarray:
    """18 columns: log_age, 8 SN-type counts, 8 Poisson errors, bin width."""
    data = _load_table(path, n_cols=18, n_rows=N_AGES)
    _validate_age_column(path, data[:, 0])
    return data


def parse_yields(path: Path) -> np.ndarray:
    """9 columns: log_age, wind H/He/Z/energy, SN energy/H/He/Z."""
    data = _load_table(path, n_cols=9, n_rows=N_AGES)
    _validate_age_column(path, data[:, 0])
    return data


def parse_mlratio(path: Path) -> np.ndarray:
    """3 columns: log_age, M/L_K, M/L_V."""
    data = _load_table(path, n_cols=3, n_rows=N_AGES)
    _validate_age_column(path, data[:, 0])
    return data


def parse_star_counts(path: Path) -> np.ndarray:
    """21 columns: log_age + 10 spectral types × 2 luminosity bins (L ≷ 4.9)."""
    data = _load_table(path, n_cols=21, n_rows=N_AGES)
    _validate_age_column(path, data[:, 0])
    return data
