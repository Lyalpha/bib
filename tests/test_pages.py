"""HTML page smoke tests. Pages must render even without a database."""

from __future__ import annotations

import pytest

from bib.config import get_branding, get_settings

PAGES = ["/", "/index.html", "/ssp", "/tutorial", "/request", "/data", "/privacy"]


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "BPASS-in-Browser" in response.text


def test_hrd_route_is_not_registered(client):
    assert client.get("/api/v1/populations/1/hrd").status_code == 404


def test_ssp_page_is_ssp_explorer(client):
    html = client.get("/ssp").text
    assert "SSP Explorer" in html
    assert "Pin SSP on plots" in html
    assert "sum visible spectra" in html
    assert "Star counts" in html
    assert "SED Explorer" not in html


def test_sed_url_redirects_to_ssp(client):
    response = client.get("/sed", follow_redirects=False)
    assert response.status_code in (301, 307, 308)
    assert response.headers["location"].endswith("/ssp")


def test_star_explorer_routes_are_gone(client):
    for path in ("/star", "/hr"):
        assert client.get(path, follow_redirects=False).status_code == 404


def test_landing_carries_official_acknowledgements(client):
    html = client.get("/").text
    assert "This work made use of v2.2.1 of the Binary Population and" in html
    assert "This work made use of v2.3 of the Binary Population and" in html
    assert "Byrne et al" in html


def test_about_redirects_to_acknowledgement(client):
    response = client.get("/about", follow_redirects=False)
    assert response.status_code in (301, 307, 308)
    assert response.headers["location"].endswith("/#acknowledgement")
    html = client.get("/").text
    assert 'id="acknowledgement"' in html
    assert "generative-AI" in html
    assert "late 2026" in html
    assert "human verification" in html


def test_tutorial_mentions_key_concepts(client):
    html = client.get("/tutorial").text
    for phrase in ("simple stellar population", "Roche-lobe", "Chabrier", "OpenDyslexic"):
        assert phrase in html, phrase
    assert 'id="imf-plot"' in html
    assert 'id="dust-plot"' in html
    assert 'id="igm-plot"' in html
    assert "dust_extinction" in html
    assert "intergalactic medium" in html
    assert "headline BPASS" not in html
    assert "Ten minutes of background" not in html


def test_privacy_page_is_short_and_linked_from_home(client):
    home = client.get("/").text
    assert home.count('href="/privacy"') >= 2
    assert "We count page views and country" in home
    html = client.get("/privacy").text
    assert "which pages are viewed" in html
    assert "how and when" in html
    assert "GoatCounter" not in html  # pixel off unless BIB_GOATCOUNTER_URL is set


def test_footer_reports_package_version_and_both_bpass_mirrors(client):
    from bib import __version__

    html = client.get("/").text
    assert f"v{__version__}" in html
    assert "Auckland mirror" in html
    assert "Warwick mirror" in html
    assert "bpass.auckland.ac.nz" in html


def test_data_page_demo_note_follows_synthetic_rows(client, monkeypatch):
    monkeypatch.setattr("bib.web.templating.has_synthetic_data", lambda: False)
    assert "synthetic toy data" not in client.get("/data").text
    monkeypatch.setattr("bib.web.templating.has_synthetic_data", lambda: True)
    html = client.get("/data").text
    assert "synthetic toy data" in html
    assert "not BPASS output" in html


def test_data_page_is_catalogue_not_ingest_guide(client):
    html = client.get("/data").text
    assert "bib ingest" not in html
    assert "bib demo-seed" not in html
    assert "source repository" in html
    assert 'href="https://github.com/Lyalpha/bib"' in html
    assert 'href="/api/docs"' in html
    assert "population_id" in html
    assert 'id="api-examples"' in html
    assert "log_age" in html


def test_data_page_links_configured_source_url(client):
    from bib.config import Branding
    from bib.web.templating import templates

    original = templates.env.globals["branding"]
    templates.env.globals["branding"] = Branding(
        site_name=original.site_name,
        full_name=original.full_name,
        source_url="https://example.org/bib",
    )
    try:
        html = client.get("/data").text
        assert 'href="https://example.org/bib"' in html
        assert "source repository" in html
    finally:
        templates.env.globals["branding"] = original


def test_api_docs_served(client):
    assert client.get("/api/docs").status_code == 200
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/v1/meta" in paths
    assert "/api/v1/populations/{population_id}/sed" in paths
    assert "/api/v1/export" in paths
    assert "/api/v1/populations/{population_id}/sed_frames" not in paths


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/v1", "/api/v1/"])
def test_api_v1_root_redirects_to_docs(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code in (302, 307, 308)
    assert response.headers["location"].endswith("/api/docs")


def test_landing_and_data_link_api_docs(client):
    home = client.get("/").text
    assert 'class="btn ghost" href="/data"' in home
    assert "SSP Explorer" in home
    assert "Fetch data" in home
    assert "Request data" not in home
    assert "Star Explorer" not in home
    assert "HR Explorer" not in home


def test_api_docs_hidden_when_disabled(monkeypatch):
    monkeypatch.setenv("BIB_EXPOSE_DOCS", "false")
    get_settings.cache_clear()
    get_branding.cache_clear()
    from fastapi.testclient import TestClient

    from bib.app import create_app

    try:
        with TestClient(create_app()) as hidden:
            assert hidden.get("/api/docs").status_code == 404
            assert hidden.get("/api/openapi.json").status_code == 404
            assert 'href="/api/docs"' not in hidden.get("/data").text
    finally:
        get_settings.cache_clear()
        get_branding.cache_clear()
