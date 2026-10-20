"""Synthetic demonstration dataset.

``bib demo-seed`` fills the database with a clearly-labelled toy dataset so the
interface can be explored with zero downloads. Shapes are physically plausible
(blackbody-mixture SEDs) but carry **no scientific content** — every row is
flagged ``is_synthetic`` and the UI shows a persistent warning banner while any
synthetic data exist.

The generator deliberately exercises the whole schema: multiple IMF labels,
sin/bin populations, alpha-enhancement variants and every per-age product table.
"""

from __future__ import annotations

import numpy as np
from rich.console import Console
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from bib.db import models as m
from bib.db.session import session_scope
from bib.ingest.parsers import ALPHA_VALUES, Z_VALUES
from bib.ingest.run import _get_or_create_grid, _insert_product_rows, _product_present
from bib.science import sed as sedlib

RELEASE_VERSION = "demo"

# physical constants (cgs)
H_ERG_S = 6.62607015e-27
C_CM_S = 2.99792458e10
K_ERG_K = 1.380649e-16
C_A_S = C_CM_S * 1e8  # Å/s
JY = 1.0e-23  # erg/s/cm^2/Hz


# ---------------------------------------------------------------------------
# toy SED synthesis
# ---------------------------------------------------------------------------


def _wavelength_grid(n: int = 16384) -> np.ndarray:
    return np.logspace(0.0, 5.0, n)  # 1 Å … 100,000 Å


def _blackbody_l_lambda(wl_a: np.ndarray, t_k: float) -> np.ndarray:
    """Unnormalised Planck L_lambda on an Å grid (arbitrary units)."""
    wl_cm = wl_a * 1e-8
    x = H_ERG_S * C_CM_S / (wl_cm * K_ERG_K * t_k)
    x = np.clip(x, 1e-6, 700.0)
    return wl_cm**-5 / np.expm1(x)


def _component(wl: np.ndarray, t_k: float, l_bol_lsun: float) -> np.ndarray:
    shape = _blackbody_l_lambda(wl, t_k)
    norm = np.trapezoid(shape, wl)
    return shape * (l_bol_lsun / norm)


def synth_sed(
    wl: np.ndarray,
    log_age: float,
    z_value: float,
    binary: bool,
    alpha: float = 0.0,
    imf_hardness: float = 1.0,
) -> np.ndarray:
    """Toy SSP SED in L_sun/Å for 1e6 Msun formed. Illustrative only."""
    age = 10.0**log_age
    zfac = (max(z_value, 1e-5) / 0.020) ** -0.045  # metal-poor => hotter

    # main-sequence turnoff component
    t_to = 42000.0 * (age / 1e6) ** -0.24 * zfac * imf_hardness
    t_to = float(np.clip(t_to, 3800.0, 55000.0))
    l_bol = 10.0 ** (9.55 - 0.82 * (log_age - 6.0))  # fading population
    l_bol = max(l_bol, 10.0**6.1)

    frac_giants = float(np.clip((log_age - 6.8) / 4.2, 0.0, 0.62))
    sed = _component(wl, t_to, l_bol * (1.0 - frac_giants))
    sed += _component(wl, 3900.0 * zfac**0.5, l_bol * frac_giants)

    if log_age < 6.9:  # very young: hot WR-ish tail
        sed += _component(wl, 9.0e4, l_bol * 0.06 * (6.9 - log_age))

    if binary and 6.9 < log_age < 8.8:  # stripped stars keep old pops blue
        strength = 0.10 * np.exp(-0.5 * ((log_age - 7.7) / 0.6) ** 2)
        sed += _component(wl, 3.2e4, l_bol * strength)

    if alpha:  # tiny alpha-enhancement tilt in the UV (demo affordance)
        tilt = 1.0 + alpha * 0.25 * np.clip((3000.0 - wl) / 3000.0, 0.0, 1.0)
        sed = sed * tilt

    return sed


# ---------------------------------------------------------------------------
# derived per-age products (computed from the toy SEDs)
# ---------------------------------------------------------------------------

_BOXCAR_BANDS: dict[str, tuple[float, float]] = {
    # crude central/half-width boxcars, Å — demo data only
    "mag_u": (3600, 300),
    "mag_b": (4400, 490),
    "mag_v": (5500, 440),
    "mag_r": (6400, 700),
    "mag_i": (7900, 750),
    "mag_j": (12350, 810),
    "mag_h": (16620, 1255),
    "mag_k": (21590, 1310),
    "sdss_u": (3551, 300),
    "sdss_g": (4686, 700),
    "sdss_r": (6165, 620),
    "sdss_i": (7481, 650),
    "sdss_z": (8931, 700),
    "f300w": (2987, 370),
    "f336w": (3344, 190),
    "f435w": (4297, 500),
    "f450w": (4520, 480),
    "f555w": (5336, 600),
    "f606w": (5887, 750),
    "f814w": (7940, 870),
}


def _boxcar_ab_mag(wl: np.ndarray, flux_lsun_a: np.ndarray, centre: float, half: float) -> float:
    sel = (wl >= centre - half) & (wl <= centre + half)
    if not np.any(sel):
        return float("nan")
    f_lambda = sedlib.flux_at_10pc(flux_lsun_a[sel])  # erg/s/cm^2/Å
    f_nu = f_lambda * (wl[sel] ** 2) / C_A_S  # erg/s/cm^2/Hz
    mean = float(np.trapezoid(f_nu, wl[sel]) / np.trapezoid(np.ones_like(f_nu), wl[sel]))
    return -2.5 * float(np.log10(max(mean, 1e-300) / (3631.0 * JY)))


def _bin_width_yr(age_index: int) -> float:
    la = sedlib.BPASS_LOG_AGES[age_index]
    if age_index == 0:
        return 10.0**6.05
    return 10.0 ** (la + 0.05) - 10.0 ** (la - 0.05)


def _derived_tables(wl: np.ndarray, seds: np.ndarray, binary: bool) -> dict[str, np.ndarray]:
    """Build colours/ionizing/starmass/supernova/yields/mlratio arrays (51 rows)."""
    ages = sedlib.BPASS_LOG_AGES
    n = ages.size

    colours = np.zeros((n, 22))
    ionizing = np.zeros((n, 5))
    starmass = np.zeros((n, 3 if binary else 2))
    supernova = np.zeros((n, 18))
    yields = np.zeros((n, 9))
    mlratio = np.zeros((n, 3))
    numbers = np.zeros((n, 21))

    for i, la in enumerate(ages):
        flux = seds[i]
        mags = {name: _boxcar_ab_mag(wl, flux, c, h) for name, (c, h) in _BOXCAR_BANDS.items()}
        colours[i, 0] = la
        colours[i, 1] = mags["mag_v"] - mags["mag_i"]
        for j, name in enumerate(
            [
                "mag_u",
                "mag_b",
                "mag_v",
                "mag_r",
                "mag_i",
                "mag_j",
                "mag_h",
                "mag_k",
                "sdss_u",
                "sdss_g",
                "sdss_r",
                "sdss_i",
                "sdss_z",
                "f300w",
                "f336w",
                "f435w",
                "f450w",
                "f555w",
                "f606w",
                "f814w",
            ],
            start=2,
        ):
            colours[i, j] = mags[name]

        # ionizing photons below 912 Å
        sel = wl < 912.0
        f_erg = flux[sel] * sedlib.L_SUN_ERG_S  # erg/s/Å
        nion = np.trapezoid(f_erg * wl[sel] * 1e-8 / (H_ERG_S * C_CM_S), wl[sel])
        log_nion = float(np.log10(max(nion, 1e30)))
        fuv = (wl >= 1556) & (wl <= 1576)
        nuv = (wl >= 2257) & (wl <= 2277)
        ionizing[i] = [
            la,
            log_nion,
            log_nion - 11.87,
            float(np.log10(np.mean(flux[fuv]) * sedlib.L_SUN_ERG_S)),
            float(np.log10(np.mean(flux[nuv]) * sedlib.L_SUN_ERG_S)),
        ]

        live = 1e6 * (0.995 - 0.44 * np.clip((la - 6.0) / 5.0, 0, 1) ** 0.75)
        starmass[i, 0] = la
        starmass[i, 1] = live
        if binary:
            starmass[i, 2] = 1e6 * 0.11 * np.clip((la - 6.6) / 4.4, 0, 1) ** 0.8

        dt = _bin_width_yr(i)
        n_iip = 6500.0 * np.exp(-0.5 * ((la - 7.05) / 0.28) ** 2)
        n_ib = 900.0 * np.exp(-0.5 * ((la - 6.75) / 0.22) ** 2) * (1.6 if binary else 1.0)
        n_ic = 600.0 * np.exp(-0.5 * ((la - 6.65) / 0.20) ** 2) * (1.5 if binary else 1.0)
        n_ia = 2200.0 * (10.0 ** (la - 9.0)) ** -0.55 if (binary and la >= 7.9) else 0.0
        n_low = 350.0 * np.exp(-0.5 * ((la - 9.3) / 0.5) ** 2) if binary else 0.0
        row = [
            la,
            n_ia,
            n_iip,
            0.35 * n_iip,
            n_ib,
            n_ic,
            0.004 * n_ic if binary else 0.0,
            0.0,
            n_low,
        ]
        errors = [np.sqrt(max(v, 0.0)) for v in row[1:]]
        supernova[i] = row + errors + [dt]

        wind_scale = 10.0 ** (-0.9 * (la - 6.0))
        yields[i] = [
            la,
            0.011 * wind_scale,
            0.004 * wind_scale,
            0.0011 * wind_scale,
            2.4e11 * wind_scale,
            (n_iip + n_ib + n_ic + n_ia) / dt * 1.0e44,
            0.006 * wind_scale,
            0.0026 * wind_scale,
            0.0009 * wind_scale,
        ]

        lv = 10.0 ** (-0.4 * (colours[i, 4] - 4.80))  # L_V/Lsun_V from abs V mag
        lk = 10.0 ** (-0.4 * (colours[i, 9] - 3.27))
        mlratio[i] = [la, live / max(lk, 1.0), live / max(lv, 1.0)]

        young = np.exp(-0.5 * ((la - 6.35) / 0.35) ** 2)
        mid = np.exp(-0.5 * ((la - 7.15) / 0.45) ** 2)
        cool = np.clip((la - 7.4) / 2.2, 0, 1)
        wr = 80.0 * young * (2.2 if binary else 1.0)
        numbers[i] = [
            la,
            900 * young,
            50 * young,
            1800 * mid,
            400 * mid,
            30 * mid,
            120 * cool,
            80 * cool,
            0.35 * wr,
            0.45 * wr,
            0.20 * wr,
            200 * young,
            8 * young,
            4000 * mid,
            2500 * (0.3 + cool),
            10 * cool,
            40 * cool,
            25 * cool,
            0.05 * wr,
            0.08 * wr,
            0.02 * wr,
        ]

    return {
        "colours": colours,
        "ionizing": ionizing,
        "starmass": starmass,
        "supernova": supernova,
        "yields": yields,
        "mlratio": mlratio,
        "numbers": numbers,
    }


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------

_DEMO_POPULATIONS: list[dict] = (
    [
        {"imf": "imf135_300", "z": z, "opt": opt, "alpha": None, "hardness": 1.0}
        for z in ("zem4", "z002", "z020")
        for opt in ("bin", "sin")
    ]
    + [{"imf": "imf_chab300", "z": "z020", "opt": "bin", "alpha": None, "hardness": 0.93}]
    + [
        {"imf": "imf135_300", "z": "z020", "opt": "bin", "alpha": a, "hardness": 1.0}
        for a in ("a-02", "a+00", "a+02", "a+04", "a+06")
    ]
)


def _seed_populations(session: Session, console: Console) -> None:
    release = session.scalar(select(m.Release).where(m.Release.version == RELEASE_VERSION))
    if release is None:
        release = m.Release(
            version=RELEASE_VERSION,
            name="Synthetic demo (not BPASS)",
            citation="No citation — synthetic demonstration data generated by bib.",
            url=None,
            notes="Toy dataset for exploring the interface. Not for science.",
        )
        session.add(release)
        session.flush()

    wl = _wavelength_grid()
    native_grid = _get_or_create_grid(session, wl, "native", "demo-native")
    edges = sedlib.make_display_edges(wl)
    display_wl, _ = sedlib.rebin_flux(wl, np.ones_like(wl), edges)
    display_grid = _get_or_create_grid(session, display_wl, "display", "demo-display")

    for spec in _DEMO_POPULATIONS:
        z_value = Z_VALUES[spec["z"]]
        alpha = spec["alpha"]
        population = m.Population(
            release_id=release.id,
            imf=spec["imf"],
            z_label=spec["z"],
            z_value=z_value,
            pop_type=spec["opt"],
            alpha_label=alpha,
            alpha_value=ALPHA_VALUES.get(alpha) if alpha else None,
            native_grid_id=native_grid.id,
            display_grid_id=display_grid.id,
            source_file="synthetic://demo-seed",
            sha256=None,
            is_synthetic=True,
            extra={
                "products": [
                    "spectra",
                    "colours",
                    "ionizing",
                    "starmass",
                    "supernova",
                    "yields",
                    "mlratio",
                    "numbers",
                ]
            },
        )
        session.add(population)
        session.flush()

        seds = np.zeros((51, wl.size))
        rows = []
        for i, la in enumerate(sedlib.BPASS_LOG_AGES):
            flux = synth_sed(
                wl,
                float(la),
                z_value,
                binary=spec["opt"] == "bin",
                alpha=ALPHA_VALUES.get(alpha, 0.0) if alpha else 0.0,
                imf_hardness=spec["hardness"],
            )
            seds[i] = flux
            _, flux_ds = sedlib.rebin_flux(wl, flux, edges)
            rows.append(
                {
                    "population_id": population.id,
                    "age_index": i,
                    "log_age": float(la),
                    "n_points": int(flux.size),
                    "flux": sedlib.encode_f32(flux),
                    "n_points_ds": int(flux_ds.size),
                    "flux_ds": sedlib.encode_f32(flux_ds),
                    "log_lbol": float(np.log10(sedlib.integrate_lbol(wl, flux))),
                }
            )
        session.execute(insert(m.Sed), rows)

        tables = _derived_tables(wl, seds, binary=spec["opt"] == "bin")
        for product, table in tables.items():
            _insert_product_rows(session, population.id, product, table)

        tag = f"{spec['imf']}/{spec['opt']}/{spec['z']}" + (f"/{alpha}" if alpha else "")
        console.print(f"  population {tag} [green]seeded[/green]")


_DEMO_PRODUCTS = (
    "colours",
    "ionizing",
    "starmass",
    "supernova",
    "yields",
    "mlratio",
    "numbers",
)


def _fill_missing_demo_products(session: Session, console: Console) -> int:
    """Add newly-introduced per-age tables to existing synthetic populations."""
    filled = 0
    pops = session.scalars(select(m.Population).where(m.Population.is_synthetic)).all()
    for pop in pops:
        missing = [p for p in _DEMO_PRODUCTS if not _product_present(session, pop.id, p)]
        if not missing:
            continue
        sed_rows = session.scalars(
            select(m.Sed).where(m.Sed.population_id == pop.id).order_by(m.Sed.age_index)
        ).all()
        grid = session.get(m.WavelengthGrid, pop.native_grid_id)
        if grid is None or len(sed_rows) != 51:
            continue
        wl = sedlib.decode_f64(grid.data, grid.n_points)
        seds = np.stack([sedlib.decode_f32(row.flux, row.n_points) for row in sed_rows])
        tables = _derived_tables(wl, seds, binary=pop.pop_type == "bin")
        extra = dict(pop.extra or {})
        loaded = list(extra.get("products") or [])
        for product in missing:
            _insert_product_rows(session, pop.id, product, tables[product])
            if product not in loaded:
                loaded.append(product)
            filled += 1
        pop.extra = {**extra, "products": loaded}
        console.print(f"  demo pop {pop.id}: filled {', '.join(missing)}")
    return filled


def purge_demo(*, console: Console | None = None) -> None:
    """Delete synthetic populations and the demo release. Does not reseed."""
    console = console or Console()
    with session_scope() as session:
        pops = session.execute(delete(m.Population).where(m.Population.is_synthetic)).rowcount
        session.execute(delete(m.Release).where(m.Release.version == RELEASE_VERSION))
    from bib.web.templating import invalidate_synthetic_cache

    invalidate_synthetic_cache()
    console.print(f"[green]removed synthetic demo data[/green] ({pops} population(s))")


def seed_demo(force: bool = False, console: Console | None = None) -> None:
    console = console or Console()
    from bib.db.bootstrap import init_database

    init_database(console=console)

    with session_scope() as session:
        existing = session.scalar(select(m.Population.id).where(m.Population.is_synthetic).limit(1))
        if existing is not None:
            if not force:
                filled = _fill_missing_demo_products(session, console)
                if filled:
                    console.print(
                        f"[green]filled missing demo products[/green] ({filled} table(s))"
                    )
                else:
                    console.print(
                        "[yellow]demo data already present — use --force to reseed[/yellow]"
                    )
                return
            console.print("removing existing synthetic data...")
            session.execute(delete(m.Population).where(m.Population.is_synthetic))
            session.execute(delete(m.Release).where(m.Release.version == RELEASE_VERSION))

        console.print("[bold]seeding synthetic demo dataset[/bold] (not for science)")
        _seed_populations(session, console)

    from bib.web.templating import invalidate_synthetic_cache

    invalidate_synthetic_cache()
    console.print("[green]demo seed complete[/green]")
