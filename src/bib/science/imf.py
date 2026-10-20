"""Parse BPASS IMF codes into human labels and ξ(log M) curves.

BPASS names broken power-laws ``imfXXX_YYY`` where ``XXX`` is 100× the
high-mass slope of ξ(log₁₀ M) (Salpeter is 1.35) and ``YYY`` is M_max in
solar masses. ``imf_chabYYY`` is Chabrier (2003) with the same high-mass
slope and cap. ``imfXXXall_YYY`` is a single power-law (no break at 0.5 M☉).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

# Low-mass dN/dM slope on the broken (Kroupa-like) piece; ξ ∝ M^{-0.30}.
_BROKEN_LOW_GAMMA = 0.30
_M_MIN = 0.1
_CHABRIER_MC = 0.079
_CHABRIER_SIGMA = 0.69
_CHABRIER_BREAK = 1.0

_CHAB = re.compile(r"^imf_chab(\d+)$")
_ALL = re.compile(r"^imf(\d+)all_(\d+)$")
_BROKEN = re.compile(r"^imf(\d+)_(\d+)$")


@dataclass(frozen=True)
class ImfInfo:
    code: str
    form: str  # chabrier | broken_powerlaw | powerlaw | unknown
    form_label: str
    alpha: float | None
    m_max: float | None

    @property
    def label(self) -> str:
        if self.form == "unknown" or self.alpha is None or self.m_max is None:
            return self.code
        return f"{self.form_label}, α={_fmt(self.alpha)}, M_max={_fmt(self.m_max)} M☉"

    @property
    def params_label(self) -> str:
        if self.alpha is None or self.m_max is None:
            return "—"
        return f"{_fmt(self.alpha)} / {_fmt(self.m_max)} M☉"

    def to_public_dict(self, *, curve: bool = False) -> dict:
        payload = {
            "code": self.code,
            "form": self.form,
            "form_label": self.form_label,
            "alpha": self.alpha,
            "m_max": self.m_max,
            "label": self.label,
            "params_label": self.params_label,
        }
        if curve and self.form != "unknown" and self.m_max and self.alpha is not None:
            mass, xi = self.curve()
            ln10 = float(np.log(10.0))
            payload["mass"] = [float(x) for x in mass]
            payload["xi"] = [float(x) for x in xi]
            payload["dndm"] = [float(y / (m * ln10)) for m, y in zip(mass, xi, strict=True)]
        return payload

    def xi(self, mass: np.ndarray) -> np.ndarray:
        """Number per dex in mass, normalised so ξ(1 M☉) = 1 where defined."""
        m = np.asarray(mass, dtype=float)
        out = np.full_like(m, np.nan, dtype=float)
        if self.form == "unknown" or self.alpha is None or self.m_max is None:
            return out
        ok = (m >= _M_MIN) & (m <= self.m_max) & np.isfinite(m)
        if not np.any(ok):
            return out
        mm = m[ok]
        if self.form == "chabrier":
            out[ok] = _chabrier_xi(mm, self.alpha)
        elif self.form == "broken_powerlaw":
            out[ok] = _broken_xi(mm, self.alpha)
        else:
            out[ok] = mm ** (-self.alpha)
        return out

    def curve(self, n: int = 96) -> tuple[np.ndarray, np.ndarray]:
        hi = float(self.m_max or 100.0)
        mass = np.logspace(np.log10(_M_MIN), np.log10(hi), n)
        return mass, self.xi(mass)


def describe_imf(code: str) -> ImfInfo:
    raw = (code or "").strip()
    if matched := _CHAB.fullmatch(raw):
        return ImfInfo(raw, "chabrier", "Chabrier", 1.35, float(matched.group(1)))
    if matched := _ALL.fullmatch(raw):
        return ImfInfo(
            raw, "powerlaw", "Power-law", int(matched.group(1)) / 100.0, float(matched.group(2))
        )
    if matched := _BROKEN.fullmatch(raw):
        return ImfInfo(
            raw,
            "broken_powerlaw",
            "Broken power-law",
            int(matched.group(1)) / 100.0,
            float(matched.group(2)),
        )
    return ImfInfo(raw or "unknown", "unknown", raw or "unknown", None, None)


def unique_imf_payloads(codes: list[str], *, curve: bool = True) -> list[dict]:
    infos = [describe_imf(code) for code in dict.fromkeys(codes)]
    infos.sort(key=lambda info: (info.m_max or 0.0, info.form, info.alpha or 0.0, info.code))
    return [info.to_public_dict(curve=curve) for info in infos]


def _fmt(value: float) -> str:
    return f"{value:g}"


def _chabrier_xi(mass: np.ndarray, alpha: float) -> np.ndarray:
    """Chabrier (2003) single-star ξ(log M), stitched to M^{-α} above 1 M☉."""
    log_m = np.log10(mass)
    log_mc = np.log10(_CHABRIER_MC)
    ln_at_break = np.exp(-((0.0 - log_mc) ** 2) / (2.0 * _CHABRIER_SIGMA**2))
    out = np.empty_like(mass)
    low = mass < _CHABRIER_BREAK
    out[low] = np.exp(-((log_m[low] - log_mc) ** 2) / (2.0 * _CHABRIER_SIGMA**2)) / ln_at_break
    out[~low] = mass[~low] ** (-alpha)
    return out


def _broken_xi(mass: np.ndarray, alpha: float) -> np.ndarray:
    """Broken power-law: ξ ∝ M^{-0.30} below 0.5 M☉, M^{-α} above."""
    break_m = 0.5
    xi_break = break_m ** (-alpha)
    out = np.empty_like(mass)
    low = mass < break_m
    out[low] = xi_break * (mass[low] / break_m) ** (-_BROKEN_LOW_GAMMA)
    out[~low] = mass[~low] ** (-alpha)
    return out
