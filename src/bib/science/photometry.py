"""Synthetic photometry: absolute AB magnitudes from BPASS SEDs.

Definition (photon-counting detector, the common case):

    m_AB = -2.5 log10( ∫ f_λ(λ) T(λ) λ dλ  /  ∫ f_ν=3631 Jy · (c/λ²) T(λ) λ dλ )

with f_λ evaluated at 10 pc from the SED's luminosity density (absolute
magnitude convention), i.e. magnitudes describe a 10^6 M_sun population at
10 pc unless rescaled. For energy-counting detectors the extra λ weight is
dropped. Filter transmissions are interpolated onto the SED grid, which is
always the full-resolution grid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from bib.science.sed import flux_at_10pc

C_A_S = 2.99792458e18  # speed of light in Å/s
AB_ZERO_FNU = 3631.0e-23  # erg/s/cm^2/Hz


@dataclass
class FilterCurve:
    """A filter transmission curve in memory."""

    name: str
    display_name: str
    wavelength: np.ndarray  # Å, ascending
    transmission: np.ndarray  # dimensionless, >= 0
    detector_type: str = "photon"  # 'photon' | 'energy'
    group: str = "custom"
    source: str | None = None
    lambda_eff: float = field(default=0.0)

    def __post_init__(self) -> None:
        if self.wavelength.size < 4:
            raise ValueError(f"filter {self.name}: needs at least 4 samples")
        if np.any(np.diff(self.wavelength) <= 0):
            order = np.argsort(self.wavelength)
            self.wavelength = self.wavelength[order]
            self.transmission = self.transmission[order]
        if np.any(self.transmission < 0):
            self.transmission = np.clip(self.transmission, 0.0, None)
        if not np.any(self.transmission > 0):
            raise ValueError(f"filter {self.name}: transmission is identically zero")
        if not self.lambda_eff:
            self.lambda_eff = pivot_wavelength(self.wavelength, self.transmission)

    @property
    def support(self) -> tuple[float, float]:
        nz = np.flatnonzero(self.transmission > 0)
        return float(self.wavelength[nz[0]]), float(self.wavelength[nz[-1]])


def pivot_wavelength(wl: np.ndarray, tr: np.ndarray) -> float:
    """Pivot wavelength: sqrt( ∫T λ dλ / ∫T dλ/λ )."""
    num = np.trapezoid(tr * wl, wl)
    den = np.trapezoid(tr / wl, wl)
    return float(np.sqrt(num / den)) if den > 0 else float(np.nan)


@dataclass
class PhotometryResult:
    filter_name: str
    ab_mag: float | None  # None when the filter falls outside the SED grid
    lambda_eff: float
    coverage: float  # fraction of the filter's support covered by the SED grid


def ab_magnitude(
    sed_wavelength: np.ndarray,
    sed_flux_lsun_a: np.ndarray,
    filt: FilterCurve,
) -> PhotometryResult:
    """Absolute AB magnitude of an SED (L_sun/Å) through one filter."""
    lo, hi = filt.support
    sed_lo, sed_hi = float(sed_wavelength[0]), float(sed_wavelength[-1])
    overlap_lo, overlap_hi = max(lo, sed_lo), min(hi, sed_hi)
    if overlap_hi <= overlap_lo:
        return PhotometryResult(filt.name, None, filt.lambda_eff, 0.0)
    coverage = (overlap_hi - overlap_lo) / (hi - lo)

    sel = (sed_wavelength >= lo) & (sed_wavelength <= hi)
    wl = sed_wavelength[sel]
    if wl.size < 4:
        # SED grid is coarser than the filter: evaluate on the filter's grid.
        wl = filt.wavelength
        flux = np.interp(wl, sed_wavelength, sed_flux_lsun_a, left=0.0, right=0.0)
        tr = filt.transmission
    else:
        flux = sed_flux_lsun_a[sel]
        tr = np.interp(wl, filt.wavelength, filt.transmission, left=0.0, right=0.0)

    f_lambda = flux_at_10pc(flux)  # erg/s/cm^2/Å at 10 pc
    ab_f_lambda = AB_ZERO_FNU * C_A_S / wl**2  # 3631 Jy expressed as f_λ

    if filt.detector_type == "photon":
        numerator = np.trapezoid(f_lambda * tr * wl, wl)
        denominator = np.trapezoid(ab_f_lambda * tr * wl, wl)
    else:
        numerator = np.trapezoid(f_lambda * tr, wl)
        denominator = np.trapezoid(ab_f_lambda * tr, wl)

    if numerator <= 0 or denominator <= 0:
        return PhotometryResult(filt.name, None, filt.lambda_eff, coverage)
    mag = -2.5 * float(np.log10(numerator / denominator))
    return PhotometryResult(filt.name, mag, filt.lambda_eff, float(coverage))


def parse_custom_filter(text: str, name: str = "custom") -> FilterCurve:
    """Parse a user-uploaded transmission curve.

    Accepts two-column ASCII (wavelength[Å], transmission), comma- or
    whitespace-separated, '#' comments ignored. Assumed photon-counting.
    """
    rows: list[tuple[float, float]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            raise ValueError(f"line {lineno}: expected two columns, got {line!r}")
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError as exc:
            if lineno == 1:  # tolerate a header line
                continue
            raise ValueError(f"line {lineno}: not numeric: {line!r}") from exc
    if len(rows) < 4:
        raise ValueError("need at least 4 (wavelength, transmission) samples")
    arr = np.asarray(rows, dtype=float)
    wl, tr = arr[:, 0], arr[:, 1]
    if np.any(wl <= 0):
        raise ValueError("wavelengths must be positive (Å)")
    if wl.max() < 100.0:
        # Looks like microns; be strict instead of guessing.
        raise ValueError("wavelengths look too small — supply Ångströms")
    return FilterCurve(
        name=name,
        display_name=name,
        wavelength=wl,
        transmission=tr,
        detector_type="photon",
        group="custom",
        source="user upload",
    )
