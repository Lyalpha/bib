"""Real-data validation against a BPASS v2.2.1 subset (marker: ``realdata``).

These tests ingest ``src/bib/ingest/subset.yaml`` (imf135_300, Z=0.002,
binaries: spectra + colours + ionizing) into the test database and compare
what bib serves with two independent references:

* **synphot** — the same SED through the same SVO curve, AB system.
  Checks bib's photon-weighted integral and unit conversion (< 1 mmag).
* **BPASS's own ``colours`` and ``ionizing`` tables** — published alongside
  the SEDs. bib's AB magnitudes are converted to Vega with the CALSPEC
  ``alpha_lyr_stis_011`` spectrum and compared with the published Vega
  magnitudes; log N_ion is recomputed from the served SED.

Tolerances are deliberately loose where the comparison is *not*
like-for-like: BPASS used its own filter curves and Vega zero-points, so a
few hundredths of a magnitude of constant offset is the expected
SVO-vs-BPASS filter difference, not a bib error. The measured residuals are
recorded in ``docs/science-notes.md``.

Skipped unless ``data/raw/bpass-subset/`` holds the fetched files and
PostgreSQL is reachable. Run with::

    uv run python scripts/fetch_bpass_subset.py
    uv run pytest -m realdata
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SUBSET_DIR = ROOT / "data" / "raw" / "bpass-subset"
MANIFEST = ROOT / "src" / "bib" / "ingest" / "subset.yaml"
VEGA_FILE = SUBSET_DIR / "alpha_lyr_stis_011.fits"
REQUIRED = (
    "spectra-bin-imf135_300.z002.dat",
    "colours-bin-imf135_300.z002.dat",
    "ionizing-bin-imf135_300.z002.dat",
    VEGA_FILE.name,
)

pytestmark = pytest.mark.realdata

# Planck constant [erg s] and c [Å/s] for the ionizing-photon integral.
H_ERG_S = 6.62607015e-27
C_A_S = 2.99792458e18
LYMAN_LIMIT_A = 912.0

# bib filter -> column of the BPASS `colours` table (0 = log age).
COLOURS_COLUMNS = {
    "sdss.u": "sdss_u",
    "sdss.g": "sdss_g",
    "sdss.r": "sdss_r",
    "sdss.i": "sdss_i",
    "sdss.z": "sdss_z",
    "johnson.b": "mag_b",
    "johnson.v": "mag_v",
    "hst.f435w": "f435w",
    "hst.f555w": "f555w",
    "hst.f606w": "f606w",
    "hst.f814w": "f814w",
    "2mass.j": "mag_j",
}
CHECK_LOG_AGES = (7.0, 8.0, 9.0, 10.0)


def _missing_files() -> list[str]:
    return [n for n in REQUIRED if not (SUBSET_DIR / n).is_file()]


@pytest.fixture(scope="module")
def subset_population(seeded_db, client):
    """Ingest the subset into the test DB; remove it again after the module."""
    missing = _missing_files()
    if missing:
        pytest.skip(f"BPASS subset not fetched: missing {missing} in {SUBSET_DIR}")
    pytest.importorskip("synphot", reason="synphot (dev dependency) not installed")

    from rich.console import Console
    from sqlalchemy import delete, select

    from bib.db import models as m
    from bib.db.session import session_scope
    from bib.ingest.run import run_ingest
    from bib.web.templating import invalidate_synthetic_cache

    stats = run_ingest(SUBSET_DIR, MANIFEST, replace=True, console=Console(quiet=True))
    assert stats.populations == 1, stats.warnings
    with session_scope() as session:
        population_id = session.scalar(
            select(m.Population.id).where(
                m.Population.is_synthetic.is_(False),
                m.Population.imf == "imf135_300",
                m.Population.z_label == "z002",
                m.Population.pop_type == "bin",
            )
        )
    assert population_id is not None
    yield population_id
    # Leave the shared test database as the rest of the suite expects it.
    with session_scope() as session:
        session.execute(delete(m.Population).where(m.Population.id == population_id))
    invalidate_synthetic_cache()


@pytest.fixture(scope="module")
def vega():
    from synphot import SourceSpectrum

    return SourceSpectrum.from_file(str(VEGA_FILE))


@pytest.fixture(scope="module")
def native_sed(subset_population):
    """Stored (float32) native SED grid and flux cube straight from the DB."""
    from sqlalchemy import select

    from bib.db import models as m
    from bib.db.session import session_scope
    from bib.science import sed as sedlib

    with session_scope() as session:
        population = session.get(m.Population, subset_population)
        grid = session.get(m.WavelengthGrid, population.native_grid_id)
        wavelength = sedlib.decode_f64(grid.data, grid.n_points)
        rows = session.scalars(
            select(m.Sed).where(m.Sed.population_id == subset_population).order_by(m.Sed.age_index)
        ).all()
        flux = np.vstack([sedlib.decode_f32(r.flux, r.n_points) for r in rows])
        log_ages = np.array([r.log_age for r in rows])
        log_lbol = np.array([r.log_lbol for r in rows], dtype=float)
    return wavelength, flux, log_ages, log_lbol


def _age_index(log_age: float) -> int:
    return round((log_age - 6.0) / 0.1)


def _bib_curve(name):
    """The exact stored curve bib integrates over (not the rounded JSON copy)."""
    from bib.db.session import session_scope
    from bib.science.filters import get_curves

    with session_scope() as session:
        (curve,) = get_curves(session, [name])
    return curve


def _synphot_mag(wavelength, flux_lsun_a, curve, system: str, vega=None) -> float:
    from synphot import Observation, SourceSpectrum, SpectralElement, units
    from synphot.models import Empirical1D

    from bib.science.sed import flux_at_10pc

    sp = SourceSpectrum(
        Empirical1D, points=wavelength, lookup_table=flux_at_10pc(flux_lsun_a) * units.FLAM
    )
    bp = SpectralElement(Empirical1D, points=curve.wavelength, lookup_table=curve.transmission)
    lo, hi = curve.support
    binset = wavelength[(wavelength >= lo - 50) & (wavelength <= hi + 50)]
    obs = Observation(sp, bp, binset=binset, force="taper")
    if system == "ab":
        return float(obs.effstim(flux_unit="abmag").value)
    return float(obs.effstim(flux_unit="vegamag", vegaspec=vega).value)


def _vega_ab_offset(curve, vega) -> float:
    """AB magnitude of Vega through ``curve`` (m_Vega = m_AB − this)."""
    from synphot import Observation, SpectralElement
    from synphot.models import Empirical1D

    bp = SpectralElement(Empirical1D, points=curve.wavelength, lookup_table=curve.transmission)
    return float(Observation(vega, bp, force="taper").effstim(flux_unit="abmag").value)


def _bib_ab(client, population_id: int, log_age: float, filters: list[str]) -> dict[str, float]:
    r = client.get(
        "/api/v1/photometry",
        params={"population_id": population_id, "log_age": log_age, "filters": ",".join(filters)},
    )
    r.raise_for_status()
    return {p["filter"]: p["ab_mag"] for p in r.json()["photometry"]}


# --------------------------------------------------------------------------- tests


def test_ingested_population_is_real_and_clean(client, subset_population):
    detail = client.get(f"/api/v1/populations/{subset_population}").json()
    assert detail["is_synthetic"] is False
    assert detail["release"].startswith("2.2")
    assert set(detail["products"]) >= {"spectra", "colours", "ionizing"}
    # v2.2.1 fixed the negative-flux bug: the fiducial file should be clean.
    assert detail["n_negative_clamped"] == 0
    assert len(detail["ages"]) == 51


def test_ab_magnitude_matches_synphot_within_1_mmag(client, subset_population, native_sed):
    wavelength, flux, _log_ages, _ = native_sed
    curve = _bib_curve("sdss.g")
    worst = 0.0
    for log_age in CHECK_LOG_AGES:
        i = _age_index(log_age)
        bib_mag = _bib_ab(client, subset_population, log_age, ["sdss.g"])["sdss.g"]
        ref = _synphot_mag(wavelength, flux[i], curve, "ab")
        worst = max(worst, abs(bib_mag - ref))
    assert worst < 1e-3, f"bib vs synphot AB in sdss.g differs by {1e3 * worst:.2f} mmag"


@pytest.mark.parametrize(
    ("filter_name", "max_abs_offset", "max_scatter"),
    [
        # Like-for-like-ish passbands: bib(SVO curve) vs BPASS(own curve + Vega ZP).
        ("sdss.g", 0.05, 0.02),
        ("johnson.v", 0.05, 0.02),
        ("hst.f555w", 0.05, 0.01),
        # NIR: constant zero-point offset expected (BPASS J vs 2MASS J); must be
        # flat with age, i.e. a filter/zero-point effect, not an SED error.
        ("2mass.j", 0.08, 0.01),
        # Added for the SDSS Vega-labelling check (plan WP5): same tolerance class.
        ("sdss.i", 0.05, 0.02),
        ("sdss.z", 0.05, 0.02),
    ],
)
def test_vega_magnitudes_track_published_colours(
    client, subset_population, vega, filter_name, max_abs_offset, max_scatter
):
    curve = _bib_curve(filter_name)
    table = client.get(
        f"/api/v1/populations/{subset_population}/timeseries", params={"table": "colours"}
    ).json()
    published = dict(
        zip(table["log_age"], table["columns"][COLOURS_COLUMNS[filter_name]], strict=True)
    )
    offset = _vega_ab_offset(curve, vega)

    deltas = []
    for log_age in CHECK_LOG_AGES:
        bib_ab = _bib_ab(client, subset_population, log_age, [filter_name])[filter_name]
        bib_vega = bib_ab - offset
        deltas.append(bib_vega - published[log_age])
    deltas = np.asarray(deltas)
    assert np.all(np.abs(deltas) < max_abs_offset), (
        f"{filter_name}: bib(Vega) − BPASS colours = {np.round(deltas, 3).tolist()} mag"
    )
    assert deltas.std() < max_scatter, (
        f"{filter_name}: age-to-age scatter {deltas.std():.4f} > {max_scatter}"
    )


def test_ionizing_photon_rate_recomputed_from_sed(client, subset_population, native_sed):
    """∫_{λ<912 Å} L_λ λ/(hc) dλ from the served SED vs BPASS's own N_ion.

    This is independent of any filter and checks the SED unit chain
    (L_sun/Å per 10^6 M_sun) end to end against a published number.
    """
    from bib.science.sed import L_SUN_ERG_S

    wavelength, flux, _log_ages, _ = native_sed
    table = client.get(
        f"/api/v1/populations/{subset_population}/timeseries", params={"table": "ionizing"}
    ).json()
    published = dict(zip(table["log_age"], table["columns"]["log_nion"], strict=True))
    sel = wavelength < LYMAN_LIMIT_A
    lam = wavelength[sel]
    worst = 0.0
    for log_age in (6.0, 6.5, 7.0, 8.0, 9.0):
        i = _age_index(log_age)
        l_lambda = flux[i][sel] * L_SUN_ERG_S  # erg/s/Å
        n_ion = np.trapezoid(l_lambda * lam / (H_ERG_S * C_A_S), lam)
        delta = np.log10(n_ion) - published[log_age]
        worst = max(worst, abs(delta))
    assert worst < 0.03, f"log N_ion from SED vs BPASS ionizing table differs by {worst:.4f} dex"


def test_log_lbol_is_finite_and_matches_trapezoid(native_sed):
    from bib.science.sed import integrate_lbol

    wavelength, flux, _, log_lbol = native_sed
    assert np.all(np.isfinite(log_lbol))
    assert np.all(np.diff(log_lbol) < 0.5)  # no jumps: a smooth fading population
    for i in (0, 10, 25, 50):
        recomputed = np.log10(integrate_lbol(wavelength, flux[i]))
        assert abs(recomputed - log_lbol[i]) < 1e-4
