"""Parsers for BPASS v2.2.1 / v2.3 data-release files.

Formats follow the BPASS v2.2 user manual READMEs exactly. All parsers accept
plain-text ``.dat`` files, transparently handling ``.gz`` compression, and
validate shape/sanity before anything reaches the database.
"""

from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass, field
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
        try:
            data = np.loadtxt(fh, ndmin=2)
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
    """22 columns: log_age, V-I, U, B, V, R, I, J, H, K, ugriz, WFPC2/ACS bands."""
    data = _load_table(path, n_cols=22, n_rows=N_AGES)
    _validate_age_column(path, data[:, 0])
    return data


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


# ---------------------------------------------------------------------------
# HR diagram isocontour files
# ---------------------------------------------------------------------------

HRS_DIAGRAMS = ("TL", "TG", "TTG")  # log T vs log L / log g / log(T^4/g)
HRS_N_CLASSES = 3  # surface X > 0.4, 0.4 > X > 1e-3, X < 1e-3
HRS_GRID = 100

# Axis definitions (manual): rows log T 0.1..10.0 step 0.1, cols -2.9..7.0 step 0.1
HRS_LOGT_AXIS = np.round(0.1 + 0.1 * np.arange(HRS_GRID), 1)
HRS_COL_AXIS = np.round(-2.9 + 0.1 * np.arange(HRS_GRID), 1)


def parse_hrs(path: Path) -> np.ndarray:
    """Parse ``hrs-<opt>-<imf>.<z>.dat`` into shape (3 diagrams, 3 classes, 51 ages, 100, 100)."""
    data = _load_table(path, n_cols=HRS_GRID)
    expected_rows = len(HRS_DIAGRAMS) * HRS_N_CLASSES * N_AGES * HRS_GRID
    if data.shape[0] != expected_rows:
        raise ParseError(
            f"{path.name}: expected {expected_rows} rows (459 grids of 100), found {data.shape[0]}"
        )
    grids = data.reshape(len(HRS_DIAGRAMS), HRS_N_CLASSES, N_AGES, HRS_GRID, HRS_GRID)
    return grids


# ---------------------------------------------------------------------------
# Stellar model (sneplot) files
# ---------------------------------------------------------------------------

# 0-based column indices into the sneplot table (manual cols are 1-based).
_SNEPLOT_COLUMNS: dict[str, int] = {
    "step": 0,
    "age_yr": 1,
    "log_r1": 2,
    "log_t1": 3,
    "log_l1": 4,
    "m1": 5,
    "he_core": 6,
    "co_core": 7,
    "one_core": 8,
    "x_surf": 10,
    "y_surf": 11,
    "c_surf": 12,
    "n_surf": 13,
    "o_surf": 14,
    "ne_surf": 15,
    "period_yr": 34,
    "log_sep": 35,
    "m2": 37,
    "dm1w": 39,
    "dm2w": 40,
    "dm1a": 41,
    "dm2a": 42,
    "dm1r": 43,
    "dm2r": 44,
    "log_r2": 46,
    "log_t2": 47,
    "log_l2": 48,
}

_BINARY_FIELDS = (
    "period_yr",
    "log_sep",
    "m2",
    "dm1w",
    "dm2w",
    "dm1a",
    "dm2a",
    "dm1r",
    "dm2r",
    "log_r2",
    "log_t2",
    "log_l2",
)


@dataclass
class TrackData:
    """Parsed stellar-model track (numpy arrays keyed like StellarModelStep)."""

    columns: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def n_steps(self) -> int:
        return int(self.columns["age_yr"].size)

    def __getitem__(self, key: str) -> np.ndarray:
        return self.columns[key]

    def get(self, key: str) -> np.ndarray | None:
        return self.columns.get(key)


def parse_sneplot(source: Path | bytes, name: str = "") -> TrackData:
    """Parse a ``sneplot*`` stellar model file (path or raw bytes from a tar)."""
    label = name or (source.name if isinstance(source, Path) else "sneplot")
    if isinstance(source, bytes):
        fh: io.TextIOBase = io.TextIOWrapper(io.BytesIO(source))
        data = np.loadtxt(fh, ndmin=2)
    else:
        with _open_text(source) as fh:
            data = np.loadtxt(fh, ndmin=2)
    if data.shape[0] < 2:
        raise ParseError(f"{label}: fewer than 2 timesteps")
    n_cols = data.shape[1]
    if n_cols < 16:
        raise ParseError(f"{label}: only {n_cols} columns — not a sneplot file")

    columns: dict[str, np.ndarray] = {}
    for key, idx in _SNEPLOT_COLUMNS.items():
        if idx < n_cols:
            columns[key] = data[:, idx].copy()
        elif key in _BINARY_FIELDS:
            columns[key] = np.full(data.shape[0], np.nan)
        else:
            raise ParseError(f"{label}: missing required column {idx + 1} ({key})")

    ages = columns["age_yr"]
    if np.any(np.diff(ages) < 0):
        raise ParseError(f"{label}: ages are not monotonically non-decreasing")

    # Exact zeros in companion estimates mean 'undefined / no companion'.
    for key in ("log_r2", "log_t2", "log_l2"):
        col = columns[key]
        col[col == 0.0] = np.nan
    m2 = columns["m2"]
    m2[m2 <= 0.0] = np.nan

    return TrackData(columns=columns)


# ---------------------------------------------------------------------------
# sneplot filename conventions
# ---------------------------------------------------------------------------

_Z_IN_NAME = re.compile(r"(zem\d|z\d{3})")


@dataclass
class ModelName:
    kind: str  # 'single' | 'primary' | 'secondary'
    z_label: str
    m1: float | None = None  # initial mass of the tracked star
    q: float | None = None  # M2/M1 (primaries)
    logp: float | None = None  # log10(P/days)
    mrem: float | None = None  # remnant companion mass (secondaries)
    raw: str = ""


def _numeric_tokens(parts: list[str]) -> list[float]:
    """Rejoin '-'-split tokens, treating empty tokens as a minus sign."""
    values: list[float] = []
    negate = False
    for token in parts:
        if token == "":
            negate = True
            continue
        value = float(token)
        values.append(-value if negate else value)
        negate = False
    return values


def parse_model_filename(filename: str) -> ModelName:
    """Classify a stellar-model filename.

    Conventions (manual, 'Stellar Models'):
      sneplot-<z>-<M1>            — single star
      sneplot-<z>-<M1>-<q>-<logP> — binary primary
      sneplot_2-<z>-<M2>-<Mrem>-<logP> — secondary (post primary death)
    """
    base = filename.rsplit("/", 1)[-1]
    stem = base.removesuffix(".gz").removesuffix(".dat")
    match = _Z_IN_NAME.search(stem)
    if not match:
        raise ParseError(f"{filename}: no metallicity label found")
    z_label = match.group(1)

    prefix = stem[: match.start()].strip("-_")
    remainder = stem[match.end() :].lstrip("-")
    values = _numeric_tokens(remainder.split("-")) if remainder else []

    secondary = prefix.startswith("sneplot_2") or prefix.endswith("_2")
    if secondary:
        if len(values) != 3:
            raise ParseError(f"{filename}: secondary model needs 3 parameters, got {values}")
        return ModelName(
            kind="secondary", z_label=z_label, m1=values[0], mrem=values[1], logp=values[2], raw=base
        )
    if len(values) == 1:
        return ModelName(kind="single", z_label=z_label, m1=values[0], raw=base)
    if len(values) == 3:
        return ModelName(
            kind="primary", z_label=z_label, m1=values[0], q=values[1], logp=values[2], raw=base
        )
    raise ParseError(f"{filename}: unexpected parameter count {values}")
