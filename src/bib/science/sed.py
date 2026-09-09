"""SED array handling: byte encoding, display downsampling, mass scaling.

Units: BPASS SEDs are L_sun per Å for a population of 10^6 M_sun formed in an
instantaneous burst (manual, 'Spectral Energy Distributions'). L_sun =
3.848e26 W (manual convention).

Full-resolution fluxes are always used for photometry and downloads; the
downsampled 'display' copy exists purely to keep interactive plots light.
"""

from __future__ import annotations

import numpy as np

L_SUN_W = 3.848e26  # W, BPASS manual convention
L_SUN_ERG_S = L_SUN_W * 1e7  # erg/s
PC_CM = 3.0856775814913673e18  # cm
TEN_PC_AREA_CM2 = 4.0 * np.pi * (10.0 * PC_CM) ** 2

# BPASS population age grid: log(age/yr) = 6.0 ... 11.0 in 0.1 dex steps.
BPASS_LOG_AGES: np.ndarray = np.round(6.0 + 0.1 * np.arange(51), 1)


# ---------------------------------------------------------------------------
# byte packing (little-endian, numpy round-trip)
# ---------------------------------------------------------------------------


def encode_f32(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(values, dtype="<f4").tobytes()


def decode_f32(buf: bytes, n_points: int | None = None) -> np.ndarray:
    arr = np.frombuffer(buf, dtype="<f4")
    if n_points is not None and arr.size != n_points:
        raise ValueError(f"expected {n_points} float32 values, got {arr.size}")
    return arr.astype(np.float64)


def encode_f64(values: np.ndarray) -> bytes:
    return np.ascontiguousarray(values, dtype="<f8").tobytes()


def decode_f64(buf: bytes, n_points: int | None = None) -> np.ndarray:
    arr = np.frombuffer(buf, dtype="<f8").copy()
    if n_points is not None and arr.size != n_points:
        raise ValueError(f"expected {n_points} float64 values, got {arr.size}")
    return arr


# ---------------------------------------------------------------------------
# display downsampling
# ---------------------------------------------------------------------------


def make_display_edges(wavelength: np.ndarray, target_points: int = 4000) -> np.ndarray:
    """Build adaptive bin edges for a display copy of an SED.

    Uses the native sampling where it is coarser than the target logarithmic
    spacing (so nothing is 'upsampled'), and log-spaced bins where the native
    grid is finer. For the BPASS 1 Å grid this keeps native sampling below
    ~350 Å and log bins above, ~2300 points total.
    """
    wl = np.asarray(wavelength, dtype=np.float64)
    lo, hi = float(wl[0]), float(wl[-1])
    if lo <= 0:
        raise ValueError("wavelengths must be positive")
    dex = np.log10(hi / lo) / target_points
    native_step = float(np.median(np.diff(wl)))

    # Below wl_break the native step exceeds the log-bin width -> keep native.
    wl_break = native_step / (np.log(10.0) * dex)
    wl_break = min(max(wl_break, lo), hi)

    native_part = wl[(wl >= lo) & (wl < wl_break)]
    if native_part.size >= 2:
        native_edges = np.concatenate(
            (
                [native_part[0] - 0.5 * native_step],
                0.5 * (native_part[1:] + native_part[:-1]),
                [native_part[-1] + 0.5 * native_step],
            )
        )
    else:
        native_edges = np.array([lo])

    log_start = max(wl_break, float(native_edges[-1]))
    n_log = max(int(np.ceil(np.log10(hi / log_start) / dex)), 1)
    log_edges = np.logspace(np.log10(log_start), np.log10(hi), n_log + 1)

    edges = np.unique(np.concatenate((native_edges, log_edges)))
    return edges


def rebin_flux(wavelength: np.ndarray, flux: np.ndarray, edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Average flux density within display bins (flux-density preserving).

    Returns (bin_centres, binned_flux). Empty bins are filled by linear
    interpolation from neighbouring bins so display traces stay continuous.
    """
    wl = np.asarray(wavelength, dtype=np.float64)
    fx = np.asarray(flux, dtype=np.float64)
    idx = np.searchsorted(edges, wl, side="right") - 1
    valid = (idx >= 0) & (idx < edges.size - 1)
    sums = np.bincount(idx[valid], weights=fx[valid], minlength=edges.size - 1)
    counts = np.bincount(idx[valid], minlength=edges.size - 1)

    centres = np.sqrt(edges[:-1] * edges[1:])  # geometric mean centre
    out = np.full(edges.size - 1, np.nan)
    nonzero = counts > 0
    out[nonzero] = sums[nonzero] / counts[nonzero]
    if not nonzero.all():
        out[~nonzero] = np.interp(centres[~nonzero], centres[nonzero], out[nonzero])
    return centres, out


def scale_by_mass(flux: np.ndarray, mass_msun: float) -> np.ndarray:
    """Rescale from the BPASS-native 1e6 Msun normalisation to ``mass_msun``."""
    return flux * (mass_msun / 1.0e6)


def integrate_lbol(wavelength: np.ndarray, flux: np.ndarray) -> float:
    """Total luminosity in L_sun (trapezoidal integral of L_lambda dlambda)."""
    return float(np.trapezoid(flux, wavelength))


def flux_at_10pc(flux_lsun_per_a: np.ndarray) -> np.ndarray:
    """Convert L_sun/Å to erg/s/cm^2/Å at 10 pc (absolute-magnitude frame)."""
    return flux_lsun_per_a * L_SUN_ERG_S / TEN_PC_AREA_CM2
