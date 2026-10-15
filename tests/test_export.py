"""Structured export: selectors in, units and formats out."""

from __future__ import annotations

import json

import numpy as np
import pytest

from bib.export.catalog import PRODUCTS, product_options


@pytest.fixture
def export_sel(demo_imf):
    return {
        "imf": demo_imf,
        "z_label": "z020",
        "pop_type": "bin",
        "log_age": 8.0,
    }


@pytest.fixture
def demo_imf(meta):
    pops = [p for p in meta["populations"] if p["z_label"] == "z020" and p["pop_type"] == "bin"]
    assert pops
    return pops[0]["imf"]


@pytest.fixture
def meta(api_client):
    return api_client.get("/api/v1/meta").json()


def test_export_options_lists_ssp_products(api_client):
    payload = api_client.get("/api/v1/export/options").json()
    keys = {p["key"] for p in payload["products"]}
    assert keys == set(PRODUCTS)
    assert {u["key"] for u in payload["units"]} == {"native", "physical"}
    assert {f["key"] for f in payload["formats"]} == {"csv", "json", "ecsv", "ascii"}
    assert all("uses_dust" in p for p in product_options())
    ionizing = next(p for p in payload["products"] if p["key"] == "ionizing")
    assert ionizing["fields"]
    assert ionizing["fields"][0]["name"] == "log_nion"
    assert ionizing["fields"][0]["physical_name"] == "nion"


def test_export_sed_csv_has_units_and_query(api_client, export_sel):
    response = api_client.get("/api/v1/export", params={**export_sel, "product": "sed", "format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    text = response.text
    assert "formed mass: 1e6 Msun" in text
    assert "column wavelength_angstrom [Å]" in text
    assert "column flux [Lsun Å^-1]" in text
    assert "extinction: none" in text
    assert "redshift: 0" in text
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert lines[0] == "wavelength_angstrom,flux"
    assert len(lines) > 20


def test_export_physical_scales_ionizing(api_client, export_sel):
    native = api_client.get(
        "/api/v1/export",
        params={**export_sel, "product": "ionizing", "units": "native", "format": "json"},
    ).json()
    physical = api_client.get(
        "/api/v1/export",
        params={**export_sel, "product": "ionizing", "units": "physical", "mass": 1.0, "format": "json"},
    ).json()
    assert native["meta"]["formed_mass_msun"] == 1e6
    assert physical["meta"]["formed_mass_msun"] == 1.0
    assert "log_nion" in native["data"]
    assert "nion" in physical["data"]
    log_n = native["data"]["log_nion"][0]
    nion = physical["data"]["nion"][0]
    if log_n is not None and nion is not None:
        np.testing.assert_allclose(nion, (10 ** log_n) / 1e6, rtol=1e-6)


def test_export_all_z_ionizing(api_client, export_sel):
    params = {**export_sel, "product": "ionizing", "all_z": True, "format": "json"}
    params.pop("z_label")
    payload = api_client.get("/api/v1/export", params=params).json()
    assert "z_label" in payload["data"]
    assert len(payload["data"]["z_label"]) >= 1
    assert payload["meta"]["all_ages"] is False


def test_export_ecsv_and_ascii(api_client, export_sel):
    ecsv = api_client.get(
        "/api/v1/export", params={**export_sel, "product": "star_counts", "format": "ecsv"}
    )
    assert ecsv.status_code == 200
    assert ecsv.text.startswith("# %ECSV 1.0")
    assert "datatype:" in ecsv.text
    ascii_body = api_client.get(
        "/api/v1/export", params={**export_sel, "product": "star_counts", "format": "ascii"}
    )
    assert ascii_body.status_code == 200
    assert "column log_age [dex (yr)]" in ascii_body.text


def test_export_rejects_ambiguous_or_missing(api_client, export_sel):
    missing = api_client.get(
        "/api/v1/export",
        params={**export_sel, "product": "sed", "z_label": "z999"},
    )
    assert missing.status_code == 404
    no_age = dict(export_sel)
    no_age.pop("log_age")
    assert api_client.get("/api/v1/export", params={**no_age, "product": "sed"}).status_code == 422


def test_export_photometry_states_redshift(api_client, export_sel):
    response = api_client.get(
        "/api/v1/export",
        params={
            **export_sel,
            "product": "photometry",
            "redshift": 0.5,
            "filters": "sdss.g",
            "format": "csv",
        },
    )
    assert response.status_code == 200
    text = response.text
    assert "redshift: 0.5" in text
    assert "column ab_mag [mag (AB)]" in text
    assert "sdss.g" in text


def test_export_products_bundle(api_client, export_sel):
    payload = api_client.get(
        "/api/v1/export", params={**export_sel, "product": "products", "format": "json"}
    ).json()
    names = [c["name"] for c in payload["columns"]]
    assert "log_age" in names
    assert any(n.startswith("ionizing__") for n in names)


def test_request_page_renders(client):
    html = client.get("/request").text
    assert "Request data" in html
    assert "As published" in html
    assert "Physical" in html
    assert 'id="btn-download"' in html
