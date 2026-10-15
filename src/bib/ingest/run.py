"""Ingest orchestration: manifest → parsers → database.

``bib ingest --source DIR`` walks a directory of downloaded BPASS products,
loads everything requested by the manifest (default: the bundled golden
subset), records provenance (source path + sha256), and is idempotent —
existing populations are skipped unless ``--replace`` is given;
missing products listed in the manifest are filled in on a re-run.

``--source`` may be a folder of unpacked ``.dat`` / ``.dat.gz`` files, or the
official IMF tarballs (``bpass_v2.2.1_imf*.tar.gz``, ``bpass_v2.3.a*.tar.gz``).
Matching archives are opened only when a requested product is not already on
disk; members are extracted into ``<source>/.bib-extract/`` and reused on
later runs.
"""

from __future__ import annotations

import hashlib
import tarfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from rich.console import Console
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from bib.db import models as m
from bib.db.session import session_scope
from bib.ingest import parsers
from bib.ingest.events import detect_events
from bib.ingest.parsers import ALPHA_VALUES, Z_VALUES, ModelName, ParseError, TrackData
from bib.ingest.tarpick import iter_models_in_dir, iter_selected_models, make_selector
from bib.science import sed as sedlib

DEFAULT_MANIFEST = Path(__file__).resolve().parent / "golden.yaml"

_PRODUCT_PARSERS = {
    "colours": parsers.parse_colours,
    "ionizing": parsers.parse_ionizing,
    "starmass": parsers.parse_starmass,
    "supernova": parsers.parse_supernova,
    "yields": parsers.parse_yields,
    "mlratio": parsers.parse_mlratio,
    "numbers": parsers.parse_star_counts,
}

_COLOURS_FIELDS = [
    "v_minus_i", "mag_u", "mag_b", "mag_v", "mag_r", "mag_i", "mag_j", "mag_h", "mag_k",
    "sdss_u", "sdss_g", "sdss_r", "sdss_i", "sdss_z",
    "f300w", "f336w", "f435w", "f450w", "f555w", "f606w", "f814w",
]
_IONIZING_FIELDS = ["log_nion", "log_l_halpha", "log_l_fuv", "log_l_nuv"]
_SN_FIELDS = [
    "n_ia", "n_iip", "n_ii_other", "n_ib", "n_ic", "n_grb", "n_pisn", "n_low_mass",
    "e_ia", "e_iip", "e_ii_other", "e_ib", "e_ic", "e_grb", "e_pisn", "e_low_mass",
    "bin_width_yr",
]
_YIELDS_FIELDS = ["wind_h", "wind_he", "wind_z", "wind_energy", "sn_energy", "sn_h", "sn_he", "sn_z"]
_MLRATIO_FIELDS = ["ml_k", "ml_v"]
_STAR_COUNT_FIELDS = [
    "n_o_hi", "n_of_hi", "n_b_hi", "n_a_hi", "n_ysg_hi",
    "n_k_hi", "n_m_hi", "n_wnh_hi", "n_wn_hi", "n_wc_hi",
    "n_o_lo", "n_of_lo", "n_b_lo", "n_a_lo", "n_ysg_lo",
    "n_k_lo", "n_m_lo", "n_wnh_lo", "n_wn_lo", "n_wc_lo",
]
_PRODUCT_MODELS = {
    "colours": m.Colours,
    "ionizing": m.Ionizing,
    "starmass": m.StarMass,
    "supernova": m.SnRates,
    "yields": m.Yields,
    "mlratio": m.MLRatio,
    "numbers": m.StarCounts,
}

_STEP_FIELDS = [
    "age_yr", "log_r1", "log_t1", "log_l1", "m1", "he_core", "co_core", "one_core",
    "x_surf", "y_surf", "c_surf", "n_surf", "o_surf", "ne_surf",
    "dm1w", "dm2w", "dm1a", "dm2a", "dm1r", "dm2r",
    "period_yr", "log_sep", "m2", "log_r2", "log_t2", "log_l2",
]


@dataclass
class IngestStats:
    populations: int = 0
    skipped_populations: int = 0
    hrd_files: int = 0
    models: int = 0
    skipped_models: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, console: Console, message: str) -> None:
        self.warnings.append(message)
        console.print(f"  [yellow]warning:[/yellow] {message}")


def _is_tar_archive(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar")


class FileIndex:
    """Name lookup over unpacked files, then IMF product tarballs.

    ``archive_needles`` (IMF labels, plus ``v2.3`` when the manifest asks for
    alpha grids) restrict which ``.tar`` / ``.tar.gz`` archives are opened, so a
    full-release download folder does not get every 500 MB tarball decompressed.
    """

    def __init__(self, root: Path, archive_needles: Iterable[str] | None = None):
        self.root = root
        self.extract_dir = root / ".bib-extract"
        self.archive_needles = {n for n in (archive_needles or []) if n}
        self.by_name: dict[str, list[Path]] = {}
        self._origin: dict[Path, str] = {}
        self._archives_scanned: set[Path] = set()
        for path in root.rglob("*"):
            if path.is_file():
                self.by_name.setdefault(path.name, []).append(path)

    def find(self, *names: str) -> Path | None:
        hit = self._lookup_loose(*names)
        if hit is not None:
            return hit
        self.prefetch(names)
        return self._lookup_loose(*names)

    def find_all_suffixed(self, prefix: str, suffix: str) -> list[Path]:
        out = []
        for name, paths in self.by_name.items():
            if name.startswith(prefix) and name.endswith(suffix):
                out.extend(paths)
        return sorted(out)

    def provenance(self, path: Path) -> str:
        if path in self._origin:
            return self._origin[path]
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def prefetch(self, names: Iterable[str], console: Console | None = None) -> None:
        """Extract any missing basenames from matching archives, one pass each."""
        missing = {n for n in self._wanted_basenames(names) if n not in self.by_name}
        if not missing:
            return
        archives = [a for a in self._matching_archives() if a not in self._archives_scanned]
        if not archives:
            return
        self.extract_dir.mkdir(parents=True, exist_ok=True)
        for archive in archives:
            if console:
                console.print(f"  reading [bold]{archive.name}[/bold] for population products...")
            extracted = self._extract_from_archive(archive, missing)
            self._archives_scanned.add(archive)
            if console and extracted:
                console.print(f"    extracted {extracted} file(s)")
            if not missing:
                break

    def _wanted_basenames(self, names: Iterable[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for name in names:
            for candidate in (name, name + ".gz"):
                if candidate not in seen:
                    seen.add(candidate)
                    out.append(candidate)
        return out

    def _lookup_loose(self, *names: str) -> Path | None:
        for name in names:
            for candidate in (name, name + ".gz"):
                hits = self.by_name.get(candidate)
                if hits:
                    return sorted(hits)[0]
        return None

    def _matching_archives(self) -> list[Path]:
        out: list[Path] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or not _is_tar_archive(path):
                continue
            if path.parent == self.extract_dir:
                continue
            if self.archive_needles and not any(n in path.name for n in self.archive_needles):
                continue
            out.append(path)
        return out

    def _register_extracted(self, dest: Path, archive: Path, member: str) -> None:
        self.by_name.setdefault(dest.name, []).append(dest)
        self._origin[dest] = self._tar_provenance(archive, member)

    def _tar_provenance(self, archive: Path, member: str) -> str:
        try:
            rel = archive.relative_to(self.root)
        except ValueError:
            rel = archive
        return f"{rel}::{Path(member).name}"

    def _claim(self, missing: set[str], basename: str) -> bool:
        if basename in missing:
            missing.discard(basename)
            if basename.endswith(".gz"):
                missing.discard(basename[:-3])
            return True
        if basename.endswith(".gz") and basename[:-3] in missing:
            missing.discard(basename[:-3])
            missing.discard(basename)
            return True
        return False

    def _extract_from_archive(self, archive: Path, missing: set[str]) -> int:
        extracted = 0
        with tarfile.open(archive, "r:*") as tf:
            for info in tf:
                if not info.isfile():
                    continue
                base = Path(info.name).name
                dest = self.extract_dir / base
                already = dest.exists() and dest.stat().st_size > 0
                if already:
                    if self._claim(missing, base) or dest.name not in self.by_name:
                        self._register_extracted(dest, archive, info.name)
                    continue
                if not self._claim(missing, base):
                    continue
                fh = tf.extractfile(info)
                if fh is None:
                    continue
                dest.write_bytes(fh.read())
                self._register_extracted(dest, archive, info.name)
                extracted += 1
                if not missing:
                    break
        return extracted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _product_filenames(
    product: str,
    opt: str,
    imf: str,
    z: str,
    alpha: str | None,
) -> list[str]:
    """Basenames for a BPASS product.

    v2.2.1: ``spectra-bin-imf135_100.z020.dat``.
    v2.3: ``spectra-bin-imf135_300.a+00.z020.dat`` (alpha tag next to Z;
    both orders are accepted).
    """
    if alpha is None:
        return [f"{product}-{opt}-{imf}.{z}.dat"]
    return [
        f"{product}-{opt}-{imf}.{alpha}.{z}.dat",
        f"{product}-{opt}-{imf}.{z}.{alpha}.dat",
    ]


def _archive_needles(spec: dict) -> set[str]:
    needles: set[str] = set()
    has_alpha = False
    for pop_spec in spec.get("populations", []):
        needles.add(pop_spec["imf"])
        if pop_spec.get("alphas"):
            has_alpha = True
    for hrs_spec in spec.get("hrs", []):
        needles.add(hrs_spec["imf"])
    # Official v2.3 packs are named bpass_v2.3.a+00.tar.gz, not imf*.
    if has_alpha:
        needles.add("v2.3")
    return needles


def _needed_product_names(spec: dict) -> list[str]:
    names: list[str] = []
    for pop_spec in spec.get("populations", []):
        imf = pop_spec["imf"]
        products = pop_spec.get("products", ["spectra"])
        alphas: list[str | None] = pop_spec.get("alphas") or [None]
        for opt in pop_spec.get("pop_types", ["bin"]):
            for z in pop_spec.get("metallicities", []):
                for alpha in alphas:
                    for product in products:
                        names.extend(_product_filenames(product, opt, imf, z, alpha))
    for hrs_spec in spec.get("hrs", []):
        imf = hrs_spec["imf"]
        for opt in hrs_spec.get("pop_types", ["bin"]):
            for z in hrs_spec.get("metallicities", []):
                names.append(f"hrs-{opt}-{imf}.{z}.dat")
    return names


def _nan_to_none(value: float) -> float | None:
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else value


# ---------------------------------------------------------------------------
# releases & wavelength grids
# ---------------------------------------------------------------------------


def _ensure_releases(session: Session, spec: dict) -> dict[str, m.Release]:
    releases: dict[str, m.Release] = {}
    for version, meta in (spec or {}).items():
        existing = session.scalar(select(m.Release).where(m.Release.version == version))
        if existing is None:
            existing = m.Release(
                version=version,
                name=(meta or {}).get("name"),
                citation=(meta or {}).get("citation"),
                url=(meta or {}).get("url"),
                notes=(meta or {}).get("notes"),
            )
            session.add(existing)
            session.flush()
        releases[version] = existing
    return releases


def _get_or_create_grid(
    session: Session, values: np.ndarray, kind: str, prefix: str
) -> m.WavelengthGrid:
    data = sedlib.encode_f64(values)
    name = f"{prefix}-{hashlib.sha256(data).hexdigest()[:10]}"
    grid = session.scalar(select(m.WavelengthGrid).where(m.WavelengthGrid.name == name))
    if grid is None:
        grid = m.WavelengthGrid(
            name=name, kind=kind, n_points=int(values.size), unit="angstrom", data=data
        )
        session.add(grid)
        session.flush()
    return grid


# ---------------------------------------------------------------------------
# populations
# ---------------------------------------------------------------------------


def _find_population(
    session: Session, release_id: int, imf: str, z: str, opt: str, alpha: str | None
) -> m.Population | None:
    stmt = select(m.Population).where(
        m.Population.release_id == release_id,
        m.Population.imf == imf,
        m.Population.z_label == z,
        m.Population.pop_type == opt,
        m.Population.alpha_label.is_(None) if alpha is None else m.Population.alpha_label == alpha,
    )
    return session.scalar(stmt)


def _ingest_population(
    session: Session,
    console: Console,
    stats: IngestStats,
    index: FileIndex,
    release: m.Release,
    imf: str,
    z: str,
    opt: str,
    alpha: str | None,
    products: list[str],
    replace: bool,
) -> None:
    tag = f"{release.version}/{imf}/{opt}/{z}" + (f"/{alpha}" if alpha else "")

    existing = _find_population(session, release.id, imf, z, opt, alpha)
    if existing is not None:
        if not replace:
            added = _fill_missing_products(
                session, console, stats, index, tag, existing, products, opt, imf, z, alpha
            )
            if added:
                stats.populations += 1
                console.print(f"  {tag}: filled {', '.join(added)}")
            else:
                stats.skipped_populations += 1
                console.print(f"  [dim]{tag}: already ingested — skipped[/dim]")
            return
        session.execute(delete(m.Population).where(m.Population.id == existing.id))
        session.flush()

    spectra_path = index.find(*_product_filenames("spectra", opt, imf, z, alpha))
    if spectra_path is None:
        stats.warn(console, f"{tag}: spectra file not found — population skipped")
        return

    console.print(f"  {tag}: parsing [bold]{spectra_path.name}[/bold]")
    spectra = parsers.parse_spectra(spectra_path)
    if spectra.n_negative_clamped:
        stats.warn(
            console,
            f"{tag}: clamped {spectra.n_negative_clamped} negative flux values to zero",
        )

    native_grid = _get_or_create_grid(session, spectra.wavelength, "native", "native")
    edges = sedlib.make_display_edges(spectra.wavelength)
    display_wl, _ = sedlib.rebin_flux(spectra.wavelength, spectra.flux[0], edges)
    display_grid = _get_or_create_grid(session, display_wl, "display", "display")

    population = m.Population(
        release_id=release.id,
        imf=imf,
        z_label=z,
        z_value=Z_VALUES.get(z, float("nan")),
        pop_type=opt,
        alpha_label=alpha,
        alpha_value=ALPHA_VALUES.get(alpha) if alpha else None,
        native_grid_id=native_grid.id,
        display_grid_id=display_grid.id,
        source_file=index.provenance(spectra_path),
        sha256=_sha256(spectra_path),
        is_synthetic=False,
        extra={"products": []},
    )
    session.add(population)
    session.flush()

    sed_rows = []
    for age_index in range(parsers.N_AGES):
        flux = spectra.flux[age_index]
        _, flux_ds = sedlib.rebin_flux(spectra.wavelength, flux, edges)
        lbol = sedlib.integrate_lbol(spectra.wavelength, flux)
        sed_rows.append(
            {
                "population_id": population.id,
                "age_index": age_index,
                "log_age": float(sedlib.BPASS_LOG_AGES[age_index]),
                "n_points": int(flux.size),
                "flux": sedlib.encode_f32(flux),
                "n_points_ds": int(flux_ds.size),
                "flux_ds": sedlib.encode_f32(flux_ds),
                "log_lbol": float(np.log10(lbol)) if lbol > 0 else None,
            }
        )
        if len(sed_rows) >= 8:
            session.execute(insert(m.Sed), sed_rows)
            sed_rows = []
    if sed_rows:
        session.execute(insert(m.Sed), sed_rows)

    loaded_products = ["spectra"]
    for product in products:
        if product == "spectra":
            continue
        if _try_insert_product(
            session, console, stats, index, tag, population.id, product, opt, imf, z, alpha
        ):
            loaded_products.append(product)

    population.extra = {"products": loaded_products}
    session.flush()
    stats.populations += 1


def _product_present(session: Session, population_id: int, product: str) -> bool:
    model = _PRODUCT_MODELS.get(product)
    if model is None:
        return True
    return (
        session.scalar(
            select(model.population_id).where(model.population_id == population_id).limit(1)
        )
        is not None
    )


def _try_insert_product(
    session: Session,
    console: Console,
    stats: IngestStats,
    index: FileIndex,
    tag: str,
    population_id: int,
    product: str,
    opt: str,
    imf: str,
    z: str,
    alpha: str | None,
) -> bool:
    parser = _PRODUCT_PARSERS.get(product)
    if parser is None:
        stats.warn(console, f"{tag}: unknown product '{product}' in manifest")
        return False
    path = index.find(*_product_filenames(product, opt, imf, z, alpha))
    if path is None:
        stats.warn(console, f"{tag}: {product} file not found — skipped")
        return False
    try:
        table = parser(path)
    except ParseError as exc:
        stats.warn(console, f"{tag}: {exc}")
        return False
    _insert_product_rows(session, population_id, product, table)
    return True


def _fill_missing_products(
    session: Session,
    console: Console,
    stats: IngestStats,
    index: FileIndex,
    tag: str,
    population: m.Population,
    products: list[str],
    opt: str,
    imf: str,
    z: str,
    alpha: str | None,
) -> list[str]:
    extra = dict(population.extra or {})
    loaded = list(extra.get("products") or ["spectra"])
    added: list[str] = []
    for product in products:
        if product == "spectra":
            continue
        if _product_present(session, population.id, product):
            if product not in loaded:
                loaded.append(product)
            continue
        if _try_insert_product(
            session, console, stats, index, tag, population.id, product, opt, imf, z, alpha
        ):
            added.append(product)
            if product not in loaded:
                loaded.append(product)
    if added or loaded != list((population.extra or {}).get("products") or []):
        population.extra = {**extra, "products": loaded}
        session.flush()
    return added


def _rows_from_table(
    population_id: int, table: np.ndarray, fields: list[str]
) -> list[dict]:
    rows = []
    for age_index in range(table.shape[0]):
        row = {
            "population_id": population_id,
            "age_index": age_index,
            "log_age": float(table[age_index, 0]),
        }
        for offset, name in enumerate(fields, start=1):
            row[name] = float(table[age_index, offset])
        rows.append(row)
    return rows


def _insert_product_rows(
    session: Session, population_id: int, product: str, table: np.ndarray
) -> None:
    if product == "colours":
        session.execute(insert(m.Colours), _rows_from_table(population_id, table, _COLOURS_FIELDS))
    elif product == "ionizing":
        session.execute(insert(m.Ionizing), _rows_from_table(population_id, table, _IONIZING_FIELDS))
    elif product == "starmass":
        rows = []
        has_remnants = table.shape[1] == 3
        for age_index in range(table.shape[0]):
            rows.append(
                {
                    "population_id": population_id,
                    "age_index": age_index,
                    "log_age": float(table[age_index, 0]),
                    "mass_stars": float(table[age_index, 1]),
                    "mass_remnants": float(table[age_index, 2]) if has_remnants else None,
                }
            )
        session.execute(insert(m.StarMass), rows)
    elif product == "supernova":
        session.execute(insert(m.SnRates), _rows_from_table(population_id, table, _SN_FIELDS))
    elif product == "yields":
        session.execute(insert(m.Yields), _rows_from_table(population_id, table, _YIELDS_FIELDS))
    elif product == "mlratio":
        session.execute(insert(m.MLRatio), _rows_from_table(population_id, table, _MLRATIO_FIELDS))
    elif product == "numbers":
        session.execute(insert(m.StarCounts), _rows_from_table(population_id, table, _STAR_COUNT_FIELDS))


# ---------------------------------------------------------------------------
# HRD isocontours
# ---------------------------------------------------------------------------


def _ingest_hrs(
    session: Session,
    console: Console,
    stats: IngestStats,
    index: FileIndex,
    release: m.Release,
    imf: str,
    z: str,
    opt: str,
    diagrams: list[str],
    replace: bool,
) -> None:
    tag = f"hrs {release.version}/{imf}/{opt}/{z}"
    population = _find_population(session, release.id, imf, z, opt, None)
    if population is None:
        stats.warn(console, f"{tag}: population not ingested — skipped")
        return

    existing = session.scalar(
        select(m.HrdGrid).where(m.HrdGrid.population_id == population.id).limit(1)
    )
    if existing is not None:
        if not replace:
            console.print(f"  [dim]{tag}: already ingested — skipped[/dim]")
            return
        session.execute(delete(m.HrdGrid).where(m.HrdGrid.population_id == population.id))

    path = index.find(f"hrs-{opt}-{imf}.{z}.dat")
    if path is None:
        stats.warn(console, f"{tag}: hrs file not found — skipped")
        return

    console.print(f"  {tag}: parsing [bold]{path.name}[/bold]")
    grids = parsers.parse_hrs(path)
    rows = []
    for d_index, diagram in enumerate(parsers.HRS_DIAGRAMS):
        if diagram not in diagrams:
            continue
        for h_class in range(parsers.HRS_N_CLASSES):
            for age_index in range(parsers.N_AGES):
                rows.append(
                    {
                        "population_id": population.id,
                        "age_index": age_index,
                        "log_age": float(sedlib.BPASS_LOG_AGES[age_index]),
                        "diagram": diagram,
                        "h_class": h_class,
                        "grid": sedlib.encode_f32(grids[d_index, h_class, age_index]),
                    }
                )
    for start in range(0, len(rows), 64):
        session.execute(insert(m.HrdGrid), rows[start : start + 64])
    stats.hrd_files += 1


# ---------------------------------------------------------------------------
# stellar models
# ---------------------------------------------------------------------------


def _ingest_models(
    session: Session,
    console: Console,
    stats: IngestStats,
    index: FileIndex,
    spec: dict,
    replace: bool,
) -> None:
    z = spec["z"]
    kind = spec.get("kind")
    select_spec = dict(spec.get("select", {}))
    limit = spec.get("limit")
    m1_range = select_spec.pop("m1_range", None)
    selector = make_selector(
        kind=kind,
        z_label=z,
        m1=select_spec.get("m1"),
        q=select_spec.get("q"),
        logp=select_spec.get("logp"),
        m1_range=tuple(m1_range) if m1_range else None,
    )
    tag = f"models {z}/{kind or 'any'}"

    found: list[tuple[ModelName, TrackData, str, str]] = []  # name, track, source, sha

    # 1) unpacked sneplot files anywhere under the source tree
    for name, path in iter_models_in_dir(index.root, selector, limit):
        try:
            track = parsers.parse_sneplot(path)
        except ParseError as exc:
            stats.warn(console, f"{tag}: {exc}")
            continue
        found.append((name, track, str(path.relative_to(index.root)), _sha256(path)))

    # 2) tar archives if the directory scan found nothing
    if not found:
        tar_names = [f"NEWBINMODS.{z}.tar", "NEWSINMODS.tar", f"NEWSINMODS.{z}.tar"]
        tars = [p for t in tar_names for p in index.by_name.get(t, [])]
        tars += index.find_all_suffixed("NEWBINMODS", ".tar") + index.find_all_suffixed(
            "NEWSINMODS", ".tar"
        )
        seen: set[Path] = set()
        for tar_path in tars:
            if tar_path in seen:
                continue
            seen.add(tar_path)
            remaining = None if limit is None else limit - len(found)
            if remaining is not None and remaining <= 0:
                break
            for name, blob in iter_selected_models(tar_path, selector, remaining):
                try:
                    track = parsers.parse_sneplot(blob, name=name.raw)
                except ParseError as exc:
                    stats.warn(console, f"{tag}: {exc}")
                    continue
                found.append(
                    (
                        name,
                        track,
                        f"{tar_path.relative_to(index.root)}::{name.raw}",
                        hashlib.sha256(blob).hexdigest(),
                    )
                )

    if not found:
        stats.warn(console, f"{tag}: no matching model files found")
        return

    for name, track, source_file, sha in found:
        existing = session.scalar(
            select(m.StellarModel).where(
                m.StellarModel.z_label == name.z_label,
                m.StellarModel.filename == name.raw,
            )
        )
        if existing is not None:
            if not replace:
                stats.skipped_models += 1
                continue
            session.execute(delete(m.StellarModel).where(m.StellarModel.id == existing.id))
            session.flush()

        _insert_model(session, name, track, source_file, sha, spec)
        stats.models += 1
        console.print(f"  {tag}: loaded [bold]{name.raw}[/bold] ({track.n_steps} steps)")


def _insert_model(
    session: Session,
    name: ModelName,
    track: TrackData,
    source_file: str,
    sha256: str,
    spec: dict,
    is_synthetic: bool = False,
) -> m.StellarModel:
    model = m.StellarModel(
        z_label=name.z_label,
        z_value=Z_VALUES.get(name.z_label, float("nan")),
        kind=name.kind,
        filename=name.raw,
        m1_init=name.m1,
        q_init=name.q,
        logp_init=name.logp,
        mrem_init=name.mrem,
        n_steps=track.n_steps,
        final_mass=float(track["m1"][-1]),
        curated=bool(spec.get("curated", False)),
        title=spec.get("title"),
        description=spec.get("description"),
        source_file=source_file,
        sha256=sha256,
        is_synthetic=is_synthetic,
    )
    session.add(model)
    session.flush()

    step_rows = []
    steps = track["step"].astype(int)
    for i in range(track.n_steps):
        row: dict = {"model_id": model.id, "step": int(steps[i])}
        for field_name in _STEP_FIELDS:
            col = track.get(field_name)
            row[field_name] = _nan_to_none(float(col[i])) if col is not None else None
        step_rows.append(row)
    for start in range(0, len(step_rows), 2000):
        session.execute(insert(m.StellarModelStep), step_rows[start : start + 2000])

    for event in detect_events(track):
        session.add(
            m.ModelEvent(
                model_id=model.id,
                event_type=event.event_type,
                step=event.step,
                age_yr=event.age_yr,
                label=event.label,
                note=event.note,
            )
        )
    session.flush()
    return model


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def run_ingest(
    source: Path,
    manifest: Path | None,
    replace: bool = False,
    console: Console | None = None,
) -> IngestStats:
    console = console or Console()
    manifest_path = manifest or DEFAULT_MANIFEST
    spec = yaml.safe_load(manifest_path.read_text())
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"source directory not found: {source}")

    console.print(f"[bold]bib ingest[/bold] — source {source}, manifest {manifest_path.name}")
    console.print("  indexing source directory...")
    index = FileIndex(source, archive_needles=_archive_needles(spec))
    needed = _needed_product_names(spec)
    if needed:
        index.prefetch(needed, console=console)
    stats = IngestStats()

    with session_scope() as session:
        releases = _ensure_releases(session, spec.get("releases", {}))

        for pop_spec in spec.get("populations", []):
            release = releases.get(str(pop_spec["release"]))
            if release is None:
                stats.warn(console, f"unknown release {pop_spec['release']} in manifest")
                continue
            alphas: list[str | None] = pop_spec.get("alphas") or [None]
            for opt in pop_spec.get("pop_types", ["bin"]):
                for z in pop_spec.get("metallicities", []):
                    for alpha in alphas:
                        _ingest_population(
                            session, console, stats, index, release,
                            pop_spec["imf"], z, opt, alpha,
                            pop_spec.get("products", ["spectra"]), replace,
                        )

        for hrs_spec in spec.get("hrs", []):
            release = releases.get(str(hrs_spec["release"]))
            if release is None:
                continue
            for opt in hrs_spec.get("pop_types", ["bin"]):
                for z in hrs_spec.get("metallicities", []):
                    _ingest_hrs(
                        session, console, stats, index, release,
                        hrs_spec["imf"], z, opt,
                        hrs_spec.get("diagrams", ["TL"]), replace,
                    )

        for model_spec in spec.get("models", []):
            _ingest_models(session, console, stats, index, model_spec, replace)

    console.print(
        f"[green]done[/green]: {stats.populations} populations "
        f"({stats.skipped_populations} skipped), {stats.hrd_files} hrs files, "
        f"{stats.models} models ({stats.skipped_models} skipped), "
        f"{len(stats.warnings)} warnings"
    )
    from bib.web.templating import invalidate_synthetic_cache

    invalidate_synthetic_cache()
    return stats
