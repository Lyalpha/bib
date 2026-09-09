"""HTML page smoke tests. Pages must render even without a database."""

from __future__ import annotations

import pytest

PAGES = ["/", "/sed", "/hr", "/tutorial", "/data", "/about"]


@pytest.mark.parametrize("path", PAGES)
def test_page_renders(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "BPASS-in-Browser" in response.text


def test_landing_carries_official_acknowledgements(client):
    html = client.get("/").text
    assert "This work made use of v2.2.1 of the Binary Population and" in html
    assert "This work made use of v2.3 of the Binary Population and" in html
    assert "Byrne et al" in html


def test_about_has_acknowledgement_anchor(client):
    html = client.get("/about").text
    assert 'id="acknowledgement"' in html  # the footer links to /about#acknowledgement


def test_tutorial_mentions_key_concepts(client):
    html = client.get("/tutorial").text
    for phrase in ("simple stellar population", "Roche-lobe", "imf135_300", "OpenDyslexic"):
        assert phrase in html, phrase


def test_data_page_documents_cli(client):
    html = client.get("/data").text
    assert "bib ingest" in html
    assert "bib demo-seed" in html


def test_api_docs_served(client):
    assert client.get("/api/docs").status_code == 200
    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/v1/meta" in paths
    assert "/api/v1/populations/{population_id}/sed" in paths
