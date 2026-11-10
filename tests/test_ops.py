"""Ops surfaces: probes, headers, stats allowlist, upload cap, sentry optional."""

from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import UploadFile
from starlette.requests import Request

from bib.api.v1.photometry import MAX_UPLOAD_BYTES, read_upload_capped, sanitize_upload_name
from bib.config import Settings, get_branding, get_settings
from bib.ops.headers import allow_goatcounter
from bib.ops.metrics import classify_route, emit_page_hit, emit_request
from bib.ops.ratelimit import is_custom_filter_post, is_limited
from bib.ops.stats import should_count


def test_health_is_dependency_free(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "version" in response.json()


def test_ready_503_is_generic(client, monkeypatch):
    def boom():
        raise RuntimeError("postgresql://bib:supersecret@db/bib SELECT 1 failed")

    monkeypatch.setattr("bib.db.session.get_engine", boom)
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "secret" not in response.text
    assert "postgresql" not in response.text.lower()
    assert "SELECT" not in response.text


def test_security_headers_present(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "geolocation=()" in response.headers["Permissions-Policy"]
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" in csp  # styles only
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert response.headers["X-Request-ID"]


def test_docs_csp_allows_swagger_cdn(client):
    response = client.get("/api/docs")
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" in csp
    home = client.get("/")
    assert "cdn.jsdelivr.net" not in home.headers["Content-Security-Policy"]
    assert "goatcounter.com" not in home.headers["Content-Security-Policy"]
    assert "goatcounter" not in home.text.lower()


def test_allow_goatcounter_adds_img_and_connect():
    csp = allow_goatcounter(
        "default-src 'self'; img-src 'self' data:; connect-src 'self';",
        "https://bib.goatcounter.com",
    )
    assert "img-src 'self' data: https://bib.goatcounter.com" in csp
    assert "connect-src 'self' https://bib.goatcounter.com" in csp
    assert allow_goatcounter("connect-src 'self';", None) == "connect-src 'self';"


def test_goatcounter_pixel_when_configured(monkeypatch):
    monkeypatch.setenv("BIB_GOATCOUNTER_URL", "https://bib.goatcounter.com/count")
    get_settings.cache_clear()
    get_branding.cache_clear()
    from fastapi.testclient import TestClient

    from bib.app import create_app

    try:
        with TestClient(create_app()) as gc_client:
            home = gc_client.get("/")
            assert home.status_code == 200
            assert 'data-goatcounter="https://bib.goatcounter.com/count"' in home.text
            assert "/static/js/goatcounter.js" in home.text
            csp = home.headers["Content-Security-Policy"]
            assert "https://bib.goatcounter.com" in csp
            assert "gc.zgo.at" not in csp
            assert "script-src 'self'" in csp
            privacy = gc_client.get("/privacy")
            assert privacy.status_code == 200
            assert "GoatCounter" in privacy.text
            assert "open-source" in privacy.text
            assert "GDPR" in privacy.text
    finally:
        get_settings.cache_clear()
        get_branding.cache_clear()


def test_stats_allowlist_skips_api_and_unknown(client):
    client.get("/")
    client.get("/api/v1/health")
    client.get("/static/css/main.css")
    client.get("/no-such-page")
    client.get("/ssp?x=1")
    snap = client.app.state.stats.snapshot()
    paths = {path for (_day, path) in snap}
    assert "/" in paths
    assert "/ssp" in paths
    assert not any(p.startswith("/api") for p in paths)
    assert not any(p.startswith("/static") for p in paths)
    assert "/no-such-page" not in paths
    assert not any("?" in p for p in paths)


def test_classify_route_keeps_cardinality_low():
    assert classify_route("/ssp") == "/ssp"
    assert classify_route("/api/v1/health") == "/api/v1/health"
    assert classify_route("/api/v1/populations/12/sed") == "api"
    assert classify_route("/_ops/login", "/_ops") == "admin"
    assert classify_route("/static/js/sed.js") == "static"
    assert classify_route("/nope") == "other"


def test_sentry_environment_defaults(monkeypatch):
    monkeypatch.delenv("BIB_SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("BIB_DEBUG", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().sentry_environment_name == "production"
        monkeypatch.setenv("BIB_DEBUG", "true")
        get_settings.cache_clear()
        assert get_settings().sentry_environment_name == "development"
        monkeypatch.setenv("BIB_SENTRY_ENVIRONMENT", "staging")
        get_settings.cache_clear()
        assert get_settings().sentry_environment_name == "staging"
    finally:
        get_settings.cache_clear()


def test_emit_metrics_are_safe_without_sentry():
    emit_request("GET", "/ssp", 200, 0.012)
    emit_request("GET", "/static/js/sed.js", 200, 0.001)
    emit_page_hit("/ssp")


def test_should_count_allowlist_only():
    assert should_count("/", "GET")
    assert should_count("/ssp", "GET")
    assert not should_count("/star", "GET")
    assert not should_count("/api/v1/health", "GET")
    assert not should_count("/", "POST")
    assert not should_count("/_ops", "GET")


def test_robots_omits_admin_path(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    body = response.text
    assert "Disallow: /api/docs" in body
    assert "/_ops" not in body
    assert "admin" not in body.lower()


def test_docs_hidden_when_explicitly_off(monkeypatch):
    monkeypatch.setenv("BIB_EXPOSE_DOCS", "false")
    get_settings.cache_clear()
    get_branding.cache_clear()
    from fastapi.testclient import TestClient

    from bib.app import create_app

    try:
        with TestClient(create_app()) as hidden:
            assert hidden.get("/api/docs").status_code == 404
            assert hidden.get("/api/openapi.json").status_code == 404
    finally:
        get_settings.cache_clear()
        get_branding.cache_clear()


def test_sentry_dsn_alias_from_env(monkeypatch):
    monkeypatch.setenv("BIB_SENTRY_DSN", "https://examplePublic@example.com/1")
    get_settings.cache_clear()
    try:
        assert get_settings().sentry_dsn == "https://examplePublic@example.com/1"
    finally:
        get_settings.cache_clear()


def test_sentry_optional_without_sdk(monkeypatch):
    monkeypatch.setenv("BIB_SENTRY_DSN", "https://examplePublic@example.com/1")
    # Do not start a real SDK client (it would try to flush events at exit).
    try:
        import sentry_sdk
    except ImportError:
        sentry_sdk = None
    if sentry_sdk is not None:
        monkeypatch.setattr(sentry_sdk, "init", lambda **_kw: None)
    get_settings.cache_clear()
    get_branding.cache_clear()
    from bib.app import create_app

    create_app()  # must not raise
    get_settings.cache_clear()
    get_branding.cache_clear()


def test_sanitize_upload_name_strips_markup():
    assert "<" not in sanitize_upload_name("<img src=x onerror=alert(1)>.txt")
    assert sanitize_upload_name("/tmp/curve.dat") == "curve.dat"
    assert sanitize_upload_name(None) == "custom"


def test_is_limited_covers_expensive_set():
    settings = Settings(admin_path="/_ops", admin_token="x")

    def req(method: str, path: str, query: str = "") -> Request:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
        return Request(scope)

    assert is_custom_filter_post(req("POST", "/api/v1/photometry/custom"))
    assert not is_custom_filter_post(req("GET", "/api/v1/photometry"))
    assert is_limited(req("POST", "/api/v1/photometry/custom"), settings)
    assert is_limited(req("GET", "/api/v1/photometry"), settings)
    assert is_limited(req("GET", "/api/v1/populations/1/sed_frames"), settings)
    assert is_limited(req("GET", "/api/v1/populations/1/sed", "resolution=native"), settings)
    assert is_limited(req("GET", "/api/v1/populations/1/sed", "format=csv"), settings)
    assert not is_limited(req("GET", "/api/v1/populations/1/sed"), settings)
    assert is_limited(req("POST", "/_ops/login"), settings)
    assert is_limited(
        req("GET", "/api/v1/export", "product=sed&z_label=z020&all_ages=true"), settings
    )
    assert not is_limited(req("GET", "/api/v1/export/options"), settings)
    assert not is_limited(req("GET", "/api/v1/health"), settings)


def test_expensive_get_rate_limited(monkeypatch):
    monkeypatch.setenv("BIB_RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    get_branding.cache_clear()
    from fastapi.testclient import TestClient

    from bib.app import create_app

    # Photometry hits the DB; TestClient must not raise 5xx when postgres is down.
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        client.get("/api/v1/photometry", params={"population_id": 1, "age_index": 0})
        client.get("/api/v1/photometry", params={"population_id": 1, "age_index": 0})
        third = client.get("/api/v1/photometry", params={"population_id": 1, "age_index": 0})
        assert third.status_code == 429
    get_settings.cache_clear()
    get_branding.cache_clear()


def test_custom_filter_post_rate_limited(monkeypatch):
    monkeypatch.setenv("BIB_CUSTOM_FILTER_RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    get_branding.cache_clear()
    from fastapi.testclient import TestClient

    from bib.app import create_app

    def _post(client):
        return client.post(
            "/api/v1/photometry/custom",
            data={"population_id": "1", "age_index": "0"},
            files={"file": ("bad.txt", b"not a filter", "text/plain")},
        )

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        assert _post(client).status_code != 429
        assert _post(client).status_code != 429
        assert _post(client).status_code == 429
        # The custom bucket is separate from the expensive-GET bucket.
        phot = client.get("/api/v1/photometry", params={"population_id": 1, "age_index": 0})
        assert phot.status_code != 429
    get_settings.cache_clear()
    get_branding.cache_clear()


def test_read_upload_capped_aborts():
    class _File:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._i = 0

        async def read(self, n: int = -1) -> bytes:
            if self._i >= len(self._data):
                return b""
            if n < 0:
                chunk = self._data[self._i :]
                self._i = len(self._data)
                return chunk
            chunk = self._data[self._i : self._i + n]
            self._i += len(chunk)
            return chunk

    async def _run() -> None:
        ok = UploadFile(filename="ok.txt", file=BytesIO(b"a" * 16))
        assert await read_upload_capped(ok) == b"a" * 16
        too_big = _File(b"x" * (MAX_UPLOAD_BYTES + 1))
        try:
            await read_upload_capped(too_big)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 413
        else:
            raise AssertionError("expected 413")

    asyncio.run(_run())
