"""API contract tests against a demo-seeded database (skipped when no DB)."""

from __future__ import annotations

import io
import math

import numpy as np
import pytest

pytestmark = pytest.mark.usefixtures("seeded_db")


@pytest.fixture(scope="module")
def meta(api_client):
    response = api_client.get("/api/v1/meta")
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="module")
def demo_population(meta):
    """A v2.2-style binary z020 population from the demo seed."""
    pops = [
        p
        for p in meta["populations"]
        if p["z_label"] == "z020" and p["pop_type"] == "bin" and p["alpha_label"] is None
    ]
    assert pops, "demo seed should provide a z020 binary population"
    return pops[0]


def test_health(api_client):
    assert api_client.get("/api/v1/health").json()["status"] == "ok"


def test_meta_shape(meta):
    assert meta["releases"], "at least one release"
    assert len(meta["log_ages"]) == 51
    assert {law["key"] for law in meta["dust_laws"]} == {"ccm89", "f99", "calzetti00", "smc"}
    assert meta["n_stellar_models"] >= 5
    assert meta["has_synthetic"] is True
    assert meta["imfs"]
    assert all("form_label" in imf and "dndm" in imf for imf in meta["imfs"])
    sample = meta["populations"][0]
    assert sample["imf_info"]["code"] == sample["imf"]
    assert "form_label" in sample["imf_info"]


def test_population_list_filters(api_client, demo_population):
    response = api_client.get("/api/v1/populations", params={"z_label": "z020", "pop_type": "bin"})
    assert response.status_code == 200
    rows = response.json()
    assert all(r["z_label"] == "z020" and r["pop_type"] == "bin" for r in rows)
    assert any(r["id"] == demo_population["id"] for r in rows)


def test_population_detail_provenance(api_client, demo_population):
    detail = api_client.get(f"/api/v1/populations/{demo_population['id']}").json()
    assert len(detail["ages"]) == 51
    assert detail["is_synthetic"] is True
    assert "source_file" in detail


def test_population_404(api_client):
    assert api_client.get("/api/v1/populations/999999").status_code == 404


def test_sed_display_and_native(api_client, demo_population):
    pid = demo_population["id"]
    display = api_client.get(
        f"/api/v1/populations/{pid}/sed", params={"age_index": 20, "resolution": "display"}
    ).json()
    native = api_client.get(f"/api/v1/populations/{pid}/sed", params={"log_age": 8.0}).json()
    assert native["resolution"] == "native"
    assert len(display["wavelength"]) == len(display["flux"])
    assert len(native["wavelength"]) == len(native["flux"])
    assert len(native["wavelength"]) >= len(display["wavelength"])
    assert native["log_age"] == pytest.approx(8.0)
    assert native["age_index"] == 20


def test_sed_log_age_preferred(api_client, demo_population):
    pid = demo_population["id"]
    by_log = api_client.get(f"/api/v1/populations/{pid}/sed", params={"log_age": 9.0}).json()
    by_index = api_client.get(f"/api/v1/populations/{pid}/sed", params={"age_index": 30}).json()
    assert by_log["age_index"] == 30
    assert by_log["log_age"] == pytest.approx(by_index["log_age"])
    missing = api_client.get(f"/api/v1/populations/{pid}/sed")
    assert missing.status_code == 422
    clash = api_client.get(
        f"/api/v1/populations/{pid}/sed", params={"log_age": 9.0, "age_index": 0}
    )
    assert clash.status_code == 422


def test_sed_mass_scaling(api_client, demo_population):
    pid = demo_population["id"]
    base = api_client.get(f"/api/v1/populations/{pid}/sed", params={"age_index": 0}).json()
    double = api_client.get(
        f"/api/v1/populations/{pid}/sed", params={"age_index": 0, "mass": 2e6}
    ).json()
    ratio = np.asarray(double["flux"]) / np.maximum(np.asarray(base["flux"]), 1e-300)
    positive = np.asarray(base["flux"]) > 0
    np.testing.assert_allclose(ratio[positive], 2.0, rtol=1e-3)


def test_sed_dust_dims_the_uv(api_client, demo_population):
    pid = demo_population["id"]
    params = {"age_index": 0}
    clean = api_client.get(f"/api/v1/populations/{pid}/sed", params=params).json()
    dusty = api_client.get(
        f"/api/v1/populations/{pid}/sed",
        params={**params, "dust_law": "ccm89", "ebv": 0.3},
    ).json()
    wl = np.asarray(clean["wavelength"])
    sel = (wl > 1500) & (wl < 3000)
    f_clean = np.asarray(clean["flux"])[sel]
    f_dusty = np.asarray(dusty["flux"])[sel]
    assert np.all(f_dusty <= f_clean + 1e-12)
    assert dusty["dust"]["a_v"] == pytest.approx(3.1 * 0.3, rel=1e-6)


def test_sed_unknown_dust_law(api_client, demo_population):
    response = api_client.get(
        f"/api/v1/populations/{demo_population['id']}/sed",
        params={"age_index": 0, "dust_law": "bogus", "ebv": 0.1},
    )
    assert response.status_code == 422


def test_sed_csv_download(api_client, demo_population):
    response = api_client.get(
        f"/api/v1/populations/{demo_population['id']}/sed",
        params={"age_index": 10, "format": "csv", "resolution": "native"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[2] == "wavelength_angstrom,flux_lsun_per_angstrom"
    assert len(lines) > 1000


def test_sed_frames_for_playback(api_client, demo_population):
    frames = api_client.get(f"/api/v1/populations/{demo_population['id']}/sed_frames").json()
    assert len(frames["frames"]) == 51
    n_wl = len(frames["wavelength"])
    assert all(len(f["flux"]) == n_wl for f in frames["frames"])


def test_timeseries_and_validation(api_client, demo_population):
    pid = demo_population["id"]
    colours = api_client.get(
        f"/api/v1/populations/{pid}/timeseries", params={"table": "colours"}
    ).json()
    assert len(colours["log_age"]) == 51
    assert "sdss_g" in colours["columns"]
    counts = api_client.get(
        f"/api/v1/populations/{pid}/timeseries", params={"table": "star_counts"}
    ).json()
    assert len(counts["log_age"]) == 51
    assert "n_o_hi" in counts["columns"]
    assert (
        api_client.get(f"/api/v1/populations/{pid}/timeseries", params={"table": "nope"})
    ).status_code == 422


def test_colours_cross_validate_photometry(api_client, demo_population):
    """The seeded colours table must agree with a direct boxcar AB computation
    on the native SED served by the API (same convention as the generator)."""
    from bib.ingest.synthetic import _BOXCAR_BANDS, _boxcar_ab_mag

    pid = demo_population["id"]
    colours = api_client.get(
        f"/api/v1/populations/{pid}/timeseries", params={"table": "colours"}
    ).json()
    for age_index in (0, 20, 45):
        sed = api_client.get(
            f"/api/v1/populations/{pid}/sed",
            params={"age_index": age_index, "resolution": "native"},
        ).json()
        wl = np.asarray(sed["wavelength"])
        flux = np.asarray(sed["flux"])
        centre, half = _BOXCAR_BANDS["sdss_g"]
        expected = _boxcar_ab_mag(wl, flux, centre, half)
        stored = colours["columns"]["sdss_g"][age_index]
        assert stored == pytest.approx(expected, abs=0.02)


def test_hrd_playback_grids(api_client, demo_population):
    import base64

    response = api_client.get(
        f"/api/v1/populations/{demo_population['id']}/hrd", params={"diagram": "TL"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["frames"]) == 51
    grid = base64.b64decode(payload["frames"][25]["grid"])
    assert len(grid) == payload["nx"] * payload["ny"]
    assert payload["scale"]["hi"] >= payload["scale"]["lo"]


def test_filters_bundled(api_client):
    filters = api_client.get("/api/v1/filters").json()
    names = {f["name"] for f in filters}
    assert {"sdss.g", "sdss.r", "2mass.j"} <= names
    groups = [f["group"] for f in filters]
    first_jwst = groups.index("JWST")
    first_galex = groups.index("GALEX")
    assert first_jwst < groups.index("HST") < groups.index("LSST") < first_galex
    curve = api_client.get("/api/v1/filters/sdss.g/curve").json()
    assert len(curve["wavelength"]) == len(curve["transmission"])
    assert max(curve["transmission"]) == pytest.approx(1.0, abs=1e-3)
    galex = api_client.get("/api/v1/filters/galex.fuv/curve").json()
    assert max(galex["transmission"]) == pytest.approx(1.0, abs=1e-3)
    assert api_client.get("/api/v1/filters/nosuch/curve").status_code == 404


def test_sed_redshift_observer_frame(api_client, demo_population):
    pid = demo_population["id"]
    rest = api_client.get(f"/api/v1/populations/{pid}/sed", params={"age_index": 20}).json()
    obs = api_client.get(
        f"/api/v1/populations/{pid}/sed", params={"age_index": 20, "redshift": 2.0}
    ).json()
    assert obs["redshift"] == 2.0
    assert "erg/s/cm2" in obs["flux_unit"]
    assert obs["luminosity_distance_mpc"] > 10000  # D_L(2) ≈ 15.5 Gpc
    assert obs["wavelength"][0] == pytest.approx(rest["wavelength"][0] * 3.0, rel=1e-4)
    assert obs["wavelength"][-1] == pytest.approx(rest["wavelength"][-1] * 3.0, rel=1e-4)


def test_photometry_redshift_distance_modulus(api_client, demo_population):
    """At tiny z the apparent mag is M + μ − 2.5log10(1+z) ± a tiny K-term."""
    pid = demo_population["id"]
    params = {"population_id": pid, "age_index": 20, "filters": "sdss.i"}
    absolute = api_client.get("/api/v1/photometry", params=params).json()
    assert absolute["frame"] == "absolute (10 pc)"

    z = 0.001
    apparent = api_client.get("/api/v1/photometry", params={**params, "redshift": z}).json()
    assert apparent["frame"] == "apparent"
    d_l_pc = apparent["luminosity_distance_mpc"] * 1e6
    mu = 5.0 * math.log10(d_l_pc / 10.0)
    shift = apparent["photometry"][0]["ab_mag"] - absolute["photometry"][0]["ab_mag"]
    assert shift == pytest.approx(mu - 2.5 * math.log10(1 + z), abs=0.05)


def test_photometry_plot_level_hugs_sed(api_client, demo_population):
    """The marker level should sit on the plotted curve (smooth SED region)."""
    pid = demo_population["id"]
    z = 1.5
    phot = api_client.get(
        "/api/v1/photometry",
        params={"population_id": pid, "age_index": 20, "filters": "sdss.i", "redshift": z},
    ).json()["photometry"][0]
    sed = api_client.get(
        f"/api/v1/populations/{pid}/sed",
        params={"age_index": 20, "resolution": "native"},
    ).json()
    wl_obs = [w * (1 + z) for w in sed["wavelength"]]
    plot_flux = [f / (1 + z) for f in sed["flux"]]
    # curve value nearest the filter's effective wavelength
    idx = min(range(len(wl_obs)), key=lambda i: abs(wl_obs[i] - phot["lambda_eff"]))
    assert phot["plot_level"] == pytest.approx(plot_flux[idx], rel=0.2)


def test_photometry_bundled_and_mass_shift(api_client, demo_population):
    pid = demo_population["id"]
    base = api_client.get(
        "/api/v1/photometry",
        params={"population_id": pid, "age_index": 20, "filters": "sdss.g,sdss.r"},
    ).json()
    mags = {r["filter"]: r["ab_mag"] for r in base["photometry"]}
    assert set(mags) == {"sdss.g", "sdss.r"}
    assert all(math.isfinite(v) for v in mags.values())

    heavier = api_client.get(
        "/api/v1/photometry",
        params={"population_id": pid, "age_index": 20, "filters": "sdss.g", "mass": 2e6},
    ).json()
    shift = heavier["photometry"][0]["ab_mag"] - mags["sdss.g"]
    # ab_mag is rounded to 4 decimals in the payload
    assert shift == pytest.approx(-2.5 * math.log10(2.0), abs=2e-4)


def test_photometry_accepts_log_age(api_client, demo_population):
    pid = demo_population["id"]
    by_log = api_client.get(
        "/api/v1/photometry",
        params={"population_id": pid, "log_age": 8.0, "filters": "sdss.g"},
    ).json()
    by_index = api_client.get(
        "/api/v1/photometry",
        params={"population_id": pid, "age_index": 20, "filters": "sdss.g"},
    ).json()
    assert by_log["log_age"] == pytest.approx(8.0)
    assert by_log["photometry"][0]["ab_mag"] == by_index["photometry"][0]["ab_mag"]


def test_photometry_unknown_filter(api_client, demo_population):
    response = api_client.get(
        "/api/v1/photometry",
        params={"population_id": demo_population["id"], "age_index": 0, "filters": "nope"},
    )
    assert response.status_code == 404


def test_custom_filter_upload_matches_local_computation(api_client, demo_population):
    from bib.science.photometry import FilterCurve, ab_magnitude

    pid = demo_population["id"]
    wl = np.linspace(4000.0, 6000.0, 60)
    tr = np.exp(-0.5 * ((wl - 5000.0) / 400.0) ** 2)
    body = "\n".join(f"{w:.2f} {t:.6f}" for w, t in zip(wl, tr, strict=True))

    response = api_client.post(
        "/api/v1/photometry/custom",
        data={"population_id": str(pid), "age_index": "20"},
        files={"file": ("myfilter.txt", io.BytesIO(body.encode()), "text/plain")},
    )
    assert response.status_code == 200
    uploaded_mag = response.json()["result"]["ab_mag"]

    sed = api_client.get(
        f"/api/v1/populations/{pid}/sed",
        params={"age_index": 20, "resolution": "native"},
    ).json()
    curve = FilterCurve(
        name="local", display_name="local", wavelength=wl, transmission=tr
    )
    local = ab_magnitude(np.asarray(sed["wavelength"]), np.asarray(sed["flux"]), curve)
    assert uploaded_mag == pytest.approx(local.ab_mag, abs=0.01)


def test_custom_filter_upload_rejects_garbage(api_client, demo_population):
    response = api_client.post(
        "/api/v1/photometry/custom",
        data={"population_id": str(demo_population["id"]), "age_index": "0"},
        files={"file": ("bad.txt", io.BytesIO(b"not a filter"), "text/plain")},
    )
    assert response.status_code == 422


def test_models_search_and_track(api_client):
    models = api_client.get("/api/v1/models").json()
    assert len(models) >= 5
    primaries = api_client.get("/api/v1/models", params={"kind": "primary"}).json()
    assert primaries and all(mm["kind"] == "primary" for mm in primaries)

    binary = next(mm for mm in primaries if mm["q_init"])
    track = api_client.get(f"/api/v1/models/{binary['id']}/track").json()
    arrays = track["arrays"]
    n = track["n_points"]
    for key in ("age_yr", "log_t1", "log_l1", "m1", "sep_rsun", "rl1_rsun", "rlof_active"):
        assert len(arrays[key]) == n, key
    assert track["events"], "curated tracks must carry events"
    event_types = {e["event_type"] for e in track["events"]}
    assert {"zams", "endpoint"} <= event_types
    assert all(0 <= e["index"] < n for e in track["events"])


def test_track_404(api_client):
    assert api_client.get("/api/v1/models/999999/track").status_code == 404
