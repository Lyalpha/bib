"""Fetch bundled filter transmission curves from the SVO Filter Profile Service.

Run once (network required); writes CSVs + filters.yaml metadata into
data/filters/, which are committed to the repository so deployments never need
network access.

    uv run python scripts/fetch_filters.py

SVO FPS: http://svo2.cab.inta-csic.es/theory/fps/
Please acknowledge: Rodrigo, C., Solano, E., 2020 (SVO Filter Profile Service);
Rodrigo, C., Solano, E., Bayo, A., 2012 (IVOA report).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import httpx
import numpy as np
import yaml
from astropy.io.votable import parse_single_table

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "filters"
FPS_URL = "http://svo2.cab.inta-csic.es/theory/fps/fps.php"

SVO_CITATION = (
    "SVO Filter Profile Service (Rodrigo & Solano 2020; Rodrigo, Solano & Bayo 2012), "
    "http://svo2.cab.inta-csic.es/theory/fps/"
)

# (bib name, SVO ID, display name, group, facility)
FILTERS: list[tuple[str, str, str, str, str]] = [
    # Johnson-Cousins
    ("johnson.u", "Generic/Johnson.U", "Johnson U", "Johnson-Cousins", "Generic"),
    ("johnson.b", "Generic/Johnson.B", "Johnson B", "Johnson-Cousins", "Generic"),
    ("johnson.v", "Generic/Johnson.V", "Johnson V", "Johnson-Cousins", "Generic"),
    ("cousins.r", "Generic/Cousins.R", "Cousins R", "Johnson-Cousins", "Generic"),
    ("cousins.i", "Generic/Cousins.I", "Cousins I", "Johnson-Cousins", "Generic"),
    # SDSS
    ("sdss.u", "SLOAN/SDSS.u", "SDSS u", "SDSS", "SLOAN"),
    ("sdss.g", "SLOAN/SDSS.g", "SDSS g", "SDSS", "SLOAN"),
    ("sdss.r", "SLOAN/SDSS.r", "SDSS r", "SDSS", "SLOAN"),
    ("sdss.i", "SLOAN/SDSS.i", "SDSS i", "SDSS", "SLOAN"),
    ("sdss.z", "SLOAN/SDSS.z", "SDSS z", "SDSS", "SLOAN"),
    # 2MASS
    ("2mass.j", "2MASS/2MASS.J", "2MASS J", "2MASS", "2MASS"),
    ("2mass.h", "2MASS/2MASS.H", "2MASS H", "2MASS", "2MASS"),
    ("2mass.ks", "2MASS/2MASS.Ks", "2MASS Ks", "2MASS", "2MASS"),
    # GALEX
    ("galex.fuv", "GALEX/GALEX.FUV", "GALEX FUV", "GALEX", "GALEX"),
    ("galex.nuv", "GALEX/GALEX.NUV", "GALEX NUV", "GALEX", "GALEX"),
    # LSST
    ("lsst.u", "LSST/LSST.u", "LSST u", "LSST", "Rubin/LSST"),
    ("lsst.g", "LSST/LSST.g", "LSST g", "LSST", "Rubin/LSST"),
    ("lsst.r", "LSST/LSST.r", "LSST r", "LSST", "Rubin/LSST"),
    ("lsst.i", "LSST/LSST.i", "LSST i", "LSST", "Rubin/LSST"),
    ("lsst.z", "LSST/LSST.z", "LSST z", "LSST", "Rubin/LSST"),
    ("lsst.y", "LSST/LSST.y", "LSST y", "LSST", "Rubin/LSST"),
    # HST
    ("hst.f275w", "HST/WFC3_UVIS2.F275W", "HST WFC3 F275W", "HST", "HST/WFC3"),
    ("hst.f336w", "HST/WFC3_UVIS2.F336W", "HST WFC3 F336W", "HST", "HST/WFC3"),
    ("hst.f435w", "HST/ACS_WFC.F435W", "HST ACS F435W", "HST", "HST/ACS"),
    ("hst.f555w", "HST/ACS_WFC.F555W", "HST ACS F555W", "HST", "HST/ACS"),
    ("hst.f606w", "HST/ACS_WFC.F606W", "HST ACS F606W", "HST", "HST/ACS"),
    ("hst.f814w", "HST/ACS_WFC.F814W", "HST ACS F814W", "HST", "HST/ACS"),
    # JWST NIRCam wide
    ("jwst.f070w", "JWST/NIRCam.F070W", "JWST F070W", "JWST", "JWST/NIRCam"),
    ("jwst.f090w", "JWST/NIRCam.F090W", "JWST F090W", "JWST", "JWST/NIRCam"),
    ("jwst.f115w", "JWST/NIRCam.F115W", "JWST F115W", "JWST", "JWST/NIRCam"),
    ("jwst.f150w", "JWST/NIRCam.F150W", "JWST F150W", "JWST", "JWST/NIRCam"),
    ("jwst.f200w", "JWST/NIRCam.F200W", "JWST F200W", "JWST", "JWST/NIRCam"),
    ("jwst.f277w", "JWST/NIRCam.F277W", "JWST F277W", "JWST", "JWST/NIRCam"),
    ("jwst.f356w", "JWST/NIRCam.F356W", "JWST F356W", "JWST", "JWST/NIRCam"),
    ("jwst.f444w", "JWST/NIRCam.F444W", "JWST F444W", "JWST", "JWST/NIRCam"),
    # Gaia DR3
    ("gaia.g", "GAIA/GAIA3.G", "Gaia G", "Gaia", "Gaia DR3"),
    ("gaia.bp", "GAIA/GAIA3.Gbp", "Gaia BP", "Gaia", "Gaia DR3"),
    ("gaia.rp", "GAIA/GAIA3.Grp", "Gaia RP", "Gaia", "Gaia DR3"),
]


def fetch_one(client: httpx.Client, svo_id: str) -> tuple[np.ndarray, np.ndarray, dict]:
    response = client.get(FPS_URL, params={"ID": svo_id}, timeout=60)
    response.raise_for_status()
    table = parse_single_table(io.BytesIO(response.content))
    wl = np.asarray(table.array["Wavelength"], dtype=float)
    tr = np.asarray(table.array["Transmission"], dtype=float)
    params = {}
    votable = table.to_table()
    for param in table.params:
        params[param.name] = param.value
    _ = votable
    return wl, tr, params


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    meta: dict[str, dict] = {}
    failures: list[str] = []
    with httpx.Client() as client:
        for name, svo_id, display, group, facility in FILTERS:
            try:
                wl, tr, params = fetch_one(client, svo_id)
            except Exception as exc:
                print(f"FAIL {svo_id}: {exc}")
                failures.append(svo_id)
                continue
            order = np.argsort(wl)
            wl, tr = wl[order], np.clip(tr[order], 0.0, None)
            peak = float(tr.max()) if tr.size else 0.0
            if peak > 0:
                tr = tr / peak
            detector = params.get("DetectorType")
            detector_type = "photon" if str(detector) in ("1", "1.0") else "energy"
            csv_path = OUT_DIR / f"{name}.csv"
            np.savetxt(
                csv_path,
                np.column_stack([wl, tr]),
                delimiter=",",
                header="wavelength_angstrom,transmission",
                comments="",
                fmt="%.6f",
            )
            meta[name] = {
                "display_name": display,
                "group": group,
                "facility": facility,
                "detector_type": detector_type,
                "svo_id": svo_id,
                "source": SVO_CITATION,
                "n_points": int(wl.size),
            }
            print(f"ok   {name:12s} {svo_id:26s} {wl.size:5d} pts  {detector_type}")

    (OUT_DIR / "filters.yaml").write_text(
        "# Bundled filter metadata — generated by scripts/fetch_filters.py\n"
        "# Curves fetched from the SVO Filter Profile Service; see 'source' fields.\n"
        + yaml.safe_dump(meta, sort_keys=True)
    )
    print(f"\nwrote {len(meta)} filters to {OUT_DIR}")
    if failures:
        print(f"failed: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
