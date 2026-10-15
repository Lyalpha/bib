"""In-memory export table: columns, units, and query metadata."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

NATIVE_MASS = 1.0e6


@dataclass
class Column:
    name: str
    unit: str
    description: str
    values: np.ndarray
    datatype: str = "float64"

    def as_list(self) -> list:
        if self.datatype == "string":
            return ["" if v is None else str(v) for v in self.values]
        out = []
        for v in np.asarray(self.values, dtype=object):
            if v is None or (isinstance(v, float) and not np.isfinite(v)):
                out.append(None)
            elif isinstance(v, (np.floating, float)):
                out.append(float(v))
            elif isinstance(v, (np.integer, int)):
                out.append(int(v))
            else:
                out.append(v)
        return out


@dataclass
class ExportTable:
    title: str
    filename: str
    comments: list[str]
    columns: list[Column]
    meta: dict = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        return 0 if not self.columns else int(len(self.columns[0].values))

    def column_records(self) -> list[dict]:
        return [
            {"name": c.name, "unit": c.unit, "description": c.description, "datatype": c.datatype}
            for c in self.columns
        ]


def mass_scale(units: str, mass: float) -> float:
    """Factor relative to the BPASS 10^6 M☉ published tables."""
    if units == "native":
        return 1.0
    return float(mass) / NATIVE_MASS


def formed_mass(units: str, mass: float) -> float:
    return NATIVE_MASS if units == "native" else float(mass)
