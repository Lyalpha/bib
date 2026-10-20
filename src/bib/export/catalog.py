"""What can be exported. The request-data page loads this via the API."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldSpec:
    name: str
    unit_native: str
    unit_physical: str
    description: str
    kind: str = "linear"  # linear | log | colour | magnitude | intensive
    source: str | None = None  # ORM attribute; defaults to name


@dataclass(frozen=True)
class ProductSpec:
    key: str
    label: str
    description: str
    allows_all_z: bool = False
    allows_all_ages: bool = True
    uses_dust: bool = False
    uses_redshift: bool = False
    uses_igm: bool = False  # IGM attenuation option (implies uses_redshift)
    uses_filters: bool = False
    uses_mass: bool = True
    table: str | None = None  # timeseries table key
    fields: tuple[FieldSpec, ...] = field(default_factory=tuple)
    bundle: bool = False


_IONIZING = (
    FieldSpec("log_nion", "dex (s^-1)", "s^-1", "H-ionizing photon rate N_ion", "log", "log_nion"),
    FieldSpec(
        "log_l_halpha", "dex (erg s^-1)", "erg s^-1", "Case B Hα luminosity", "log", "log_l_halpha"
    ),
    FieldSpec(
        "log_l_fuv",
        "dex (erg s^-1 Å^-1)",
        "erg s^-1 Å^-1",
        "FUV luminosity density (1556–1576 Å)",
        "log",
        "log_l_fuv",
    ),
    FieldSpec(
        "log_l_nuv",
        "dex (erg s^-1 Å^-1)",
        "erg s^-1 Å^-1",
        "NUV luminosity density (2257–2277 Å)",
        "log",
        "log_l_nuv",
    ),
)

_COLOURS = (
    FieldSpec("v_minus_i", "mag (Vega)", "mag (Vega)", "V−I colour", "colour"),
    FieldSpec("mag_u", "mag (Vega)", "mag (Vega)", "Johnson-Cousins U", "magnitude"),
    FieldSpec("mag_b", "mag (Vega)", "mag (Vega)", "Johnson-Cousins B", "magnitude"),
    FieldSpec("mag_v", "mag (Vega)", "mag (Vega)", "Johnson-Cousins V", "magnitude"),
    FieldSpec("mag_r", "mag (Vega)", "mag (Vega)", "Johnson-Cousins R", "magnitude"),
    FieldSpec("mag_i", "mag (Vega)", "mag (Vega)", "Johnson-Cousins I", "magnitude"),
    FieldSpec("mag_j", "mag (Vega)", "mag (Vega)", "2MASS/Johnson J", "magnitude"),
    FieldSpec("mag_h", "mag (Vega)", "mag (Vega)", "2MASS/Johnson H", "magnitude"),
    FieldSpec("mag_k", "mag (Vega)", "mag (Vega)", "2MASS/Johnson K", "magnitude"),
    FieldSpec("sdss_u", "mag (Vega)", "mag (Vega)", "SDSS u", "magnitude"),
    FieldSpec("sdss_g", "mag (Vega)", "mag (Vega)", "SDSS g", "magnitude"),
    FieldSpec("sdss_r", "mag (Vega)", "mag (Vega)", "SDSS r", "magnitude"),
    FieldSpec("sdss_i", "mag (Vega)", "mag (Vega)", "SDSS i", "magnitude"),
    FieldSpec("sdss_z", "mag (Vega)", "mag (Vega)", "SDSS z", "magnitude"),
    FieldSpec("f300w", "mag (Vega)", "mag (Vega)", "HST F300W", "magnitude"),
    FieldSpec("f336w", "mag (Vega)", "mag (Vega)", "HST F336W", "magnitude"),
    FieldSpec("f435w", "mag (Vega)", "mag (Vega)", "HST F435W", "magnitude"),
    FieldSpec("f450w", "mag (Vega)", "mag (Vega)", "HST F450W", "magnitude"),
    FieldSpec("f555w", "mag (Vega)", "mag (Vega)", "HST F555W", "magnitude"),
    FieldSpec("f606w", "mag (Vega)", "mag (Vega)", "HST F606W", "magnitude"),
    FieldSpec("f814w", "mag (Vega)", "mag (Vega)", "HST F814W", "magnitude"),
)

_STARMASS = (
    FieldSpec(
        "mass_stars", "Msun / 1e6 Msun formed", "Msun", "Mass remaining in live stars", "linear"
    ),
    FieldSpec(
        "mass_remnants",
        "Msun / 1e6 Msun formed",
        "Msun",
        "Mass in remnants (WD/NS/BH); binary files only",
        "linear",
    ),
)

_SN = (
    FieldSpec("n_ia", "count / 1e6 Msun / bin", "yr^-1", "Type Ia supernovae", "linear"),
    FieldSpec("n_iip", "count / 1e6 Msun / bin", "yr^-1", "Type IIP supernovae", "linear"),
    FieldSpec(
        "n_ii_other", "count / 1e6 Msun / bin", "yr^-1", "Other Type II supernovae", "linear"
    ),
    FieldSpec("n_ib", "count / 1e6 Msun / bin", "yr^-1", "Type Ib supernovae", "linear"),
    FieldSpec("n_ic", "count / 1e6 Msun / bin", "yr^-1", "Type Ic supernovae", "linear"),
    FieldSpec("n_grb", "count / 1e6 Msun / bin", "yr^-1", "Long GRB (QHE pathway)", "linear"),
    FieldSpec("n_pisn", "count / 1e6 Msun / bin", "yr^-1", "Pair-instability supernovae", "linear"),
    FieldSpec("n_low_mass", "count / 1e6 Msun / bin", "yr^-1", "Low-mass transients", "linear"),
    FieldSpec(
        "bin_width_yr", "yr", "yr", "Age-bin width (for converting counts to rates)", "intensive"
    ),
)

_YIELDS = (
    FieldSpec(
        "wind_h",
        "Msun yr^-1 / 1e6 Msun formed",
        "Msun yr^-1",
        "Hydrogen in stellar winds",
        "linear",
    ),
    FieldSpec(
        "wind_he", "Msun yr^-1 / 1e6 Msun formed", "Msun yr^-1", "Helium in stellar winds", "linear"
    ),
    FieldSpec(
        "wind_z", "Msun yr^-1 / 1e6 Msun formed", "Msun yr^-1", "Metals in stellar winds", "linear"
    ),
    FieldSpec(
        "wind_energy",
        "Msun m^2 s^-2 yr^-1 / 1e6 Msun formed",
        "Msun m^2 s^-2 yr^-1",
        "Wind mechanical energy (BPASS units)",
        "linear",
    ),
    FieldSpec("sn_energy", "J yr^-1 / 1e6 Msun formed", "J yr^-1", "Supernova energy", "linear"),
    FieldSpec(
        "sn_h",
        "Msun yr^-1 / 1e6 Msun formed",
        "Msun yr^-1",
        "Hydrogen in supernova ejecta",
        "linear",
    ),
    FieldSpec(
        "sn_he",
        "Msun yr^-1 / 1e6 Msun formed",
        "Msun yr^-1",
        "Helium in supernova ejecta",
        "linear",
    ),
    FieldSpec(
        "sn_z", "Msun yr^-1 / 1e6 Msun formed", "Msun yr^-1", "Metals in supernova ejecta", "linear"
    ),
)

_ML = (
    FieldSpec("ml_k", "Msun / Lsun", "Msun / Lsun", "Mass-to-light ratio in K", "intensive"),
    FieldSpec("ml_v", "Msun / Lsun", "Msun / Lsun", "Mass-to-light ratio in V", "intensive"),
)

_COUNT_TYPES = {
    "o": "O-type stars",
    "of": "Of stars (O-type with strong emission lines)",
    "b": "B-type stars",
    "a": "A-type stars",
    "ysg": "yellow supergiants",
    "k": "K-type stars",
    "m": "M-type stars",
    "wnh": "hydrogen-rich Wolf–Rayet (WNH) stars",
    "wn": "WN Wolf–Rayet stars",
    "wc": "WC Wolf–Rayet stars",
}


def _count_field(name: str) -> FieldSpec:
    kind, band = name[2:].rsplit("_", 1)
    luminosity = "log L/L☉ > 4.9" if band == "hi" else "log L/L☉ ≤ 4.9"
    return FieldSpec(
        name,
        "stars / 1e6 Msun formed",
        "stars",
        f"Expected number of {_COUNT_TYPES[kind]} with {luminosity} (Eldridge et al. 2017, table 3)",
        "linear",
    )


_COUNTS = tuple(
    _count_field(name)
    for name in (
        "n_o_hi",
        "n_of_hi",
        "n_b_hi",
        "n_a_hi",
        "n_ysg_hi",
        "n_k_hi",
        "n_m_hi",
        "n_wnh_hi",
        "n_wn_hi",
        "n_wc_hi",
        "n_o_lo",
        "n_of_lo",
        "n_b_lo",
        "n_a_lo",
        "n_ysg_lo",
        "n_k_lo",
        "n_m_lo",
        "n_wnh_lo",
        "n_wn_lo",
        "n_wc_lo",
    )
)


PRODUCTS: dict[str, ProductSpec] = {
    "sed": ProductSpec(
        key="sed",
        label="Spectral energy distribution",
        description="Rest-frame (or observer-frame) spectrum at native wavelength sampling.",
        allows_all_z=False,
        uses_dust=True,
        uses_redshift=True,
        uses_igm=True,
    ),
    "photometry": ProductSpec(
        key="photometry",
        label="Photometry",
        description="AB magnitudes through bundled filters, computed on the native SED.",
        allows_all_z=False,
        uses_dust=True,
        uses_redshift=True,
        uses_igm=True,
        uses_filters=True,
    ),
    "ionizing": ProductSpec(
        key="ionizing",
        label="Ionizing photons",
        description="N_ion and UV/Hα luminosities from the BPASS ionizing tables.",
        allows_all_z=True,
        table="ionizing",
        fields=_IONIZING,
    ),
    "star_counts": ProductSpec(
        key="star_counts",
        label="Star counts",
        description="IMF-weighted expected numbers by spectral type (Eldridge et al. 2017, table 3).",
        allows_all_z=True,
        table="star_counts",
        fields=_COUNTS,
    ),
    "sn_rates": ProductSpec(
        key="sn_rates",
        label="Supernova rates",
        description="Supernovae per age bin (native) or per year (physical).",
        allows_all_z=True,
        table="sn_rates",
        fields=_SN,
    ),
    "starmass": ProductSpec(
        key="starmass",
        label="Surviving mass",
        description="Mass still in live stars and remnants.",
        allows_all_z=True,
        table="starmass",
        fields=_STARMASS,
    ),
    "yields": ProductSpec(
        key="yields",
        label="Chemical yields",
        description="Wind and supernova mass and energy output rates.",
        allows_all_z=True,
        table="yields",
        fields=_YIELDS,
    ),
    "colours": ProductSpec(
        key="colours",
        label="Published colours",
        description="BPASS Vega magnitudes and colours (not the AB photometry engine).",
        allows_all_z=True,
        table="colours",
        fields=_COLOURS,
    ),
    "mlratio": ProductSpec(
        key="mlratio",
        label="Mass-to-light ratios",
        description="K- and V-band M/L in solar units.",
        allows_all_z=True,
        uses_mass=False,
        table="mlratio",
        fields=_ML,
    ),
    "products": ProductSpec(
        key="products",
        label="Population properties",
        description="Every per-age table for this population: ionizing flux, star counts, supernova rates, surviving mass, yields, colours and mass-to-light.",
        allows_all_z=False,
        bundle=True,
    ),
}


def physical_field_name(field: FieldSpec, product_key: str) -> str:
    if field.kind == "log" and field.name.startswith("log_"):
        return field.name[4:]
    if product_key == "sn_rates" and field.name.startswith("n_"):
        return f"rate_{field.name[2:]}"
    return field.name


EXPORT_UNITS = (
    {
        "key": "native",
        "label": "As published by BPASS",
        "description": "Values as in the release files: 10^6 M☉ formed at t=0. Logarithmic columns stay logarithmic.",
    },
    {
        "key": "physical",
        "label": "Physical units",
        "description": "Scaled to the formed mass on the slider. Logarithmic columns become linear values.",
    },
)

EXPORT_FORMATS = (
    {
        "key": "csv",
        "label": "CSV",
        "media": "text/csv",
        "ext": "csv",
        "note": "Comma-separated values",
    },
    {
        "key": "json",
        "label": "JSON",
        "media": "application/json",
        "ext": "json",
        "note": "One JSON object",
    },
    {
        "key": "ecsv",
        "label": "ECSV",
        "media": "text/plain",
        "ext": "ecsv",
        "note": "Enhanced CSV, for Astropy",
    },
    {
        "key": "ascii",
        "label": "ASCII",
        "media": "text/plain",
        "ext": "dat",
        "note": "Space-separated columns",
    },
)


def product_options() -> list[dict]:
    return [
        {
            "key": p.key,
            "label": p.label,
            "description": p.description,
            "allows_all_z": p.allows_all_z,
            "allows_all_ages": p.allows_all_ages,
            "uses_dust": p.uses_dust,
            "uses_redshift": p.uses_redshift,
            "uses_igm": p.uses_igm,
            "uses_filters": p.uses_filters,
            "uses_mass": p.uses_mass,
            "bundle": p.bundle,
            "fields": [
                {
                    "name": f.name,
                    "physical_name": physical_field_name(f, p.key),
                    "unit_native": f.unit_native,
                    "unit_physical": f.unit_physical,
                    "description": f.description,
                    "kind": f.kind,
                }
                for f in p.fields
            ],
        }
        for p in PRODUCTS.values()
    ]
