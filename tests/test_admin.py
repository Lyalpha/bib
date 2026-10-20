"""Operator console: 404 when unset; 401/200 when a token is configured."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from bib.config import get_branding, get_settings


def _client_with_token(token: str = "test-token-xyz", path: str = "/_ops") -> TestClient:
    os.environ["BIB_ADMIN_TOKEN"] = token
    os.environ["BIB_ADMIN_PATH"] = path
    get_settings.cache_clear()
    get_branding.cache_clear()
    from bib.app import create_app

    return TestClient(create_app())


def _clear_admin_env() -> None:
    os.environ.pop("BIB_ADMIN_TOKEN", None)
    os.environ.pop("BIB_ADMIN_PATH", None)
    get_settings.cache_clear()
    get_branding.cache_clear()


def test_admin_404_without_token_matches_missing_page(client):
    missing = client.get("/this-page-does-not-exist")
    admin = client.get("/_ops")
    assert admin.status_code == 404
    assert admin.status_code == missing.status_code
    assert admin.json() == missing.json()


def test_admin_401_and_200_with_token():
    token = "test-token-xyz"
    try:
        with _client_with_token(token) as client:
            denied = client.get("/_ops")
            assert denied.status_code == 401
            assert "Operator sign-in" in denied.text

            wrong = client.get("/_ops", headers={"Authorization": "Bearer nope"})
            assert wrong.status_code == 401

            ok = client.get("/_ops", headers={"Authorization": f"Bearer {token}"})
            assert ok.status_code == 200
            assert "Operator console" in ok.text
            assert "Visit counts" in ok.text
            assert "Recent warnings" in ok.text

            login = client.post("/_ops/login", data={"token": token}, follow_redirects=False)
            assert login.status_code in {302, 303}
            cookie = login.cookies.get("bib_ops")
            assert cookie and cookie != token  # hashed session value, never the raw token
            assert token not in cookie
            # the hashed cookie value is not accepted as a bearer token
            saved = client.cookies.get("bib_ops")
            client.cookies.delete("bib_ops")
            assert (
                client.get("/_ops", headers={"Authorization": f"Bearer {cookie}"}).status_code
                == 401
            )
            client.cookies.set("bib_ops", saved)
            header = login.headers.get("set-cookie", "")
            assert "HttpOnly" in header
            assert "samesite=strict" in header.lower()
            assert "Path=/_ops" in header

            authed = client.get("/_ops")
            assert authed.status_code == 200
    finally:
        _clear_admin_env()


def test_admin_token_not_accepted_in_query():
    token = "test-token-xyz"
    try:
        with _client_with_token(token) as client:
            leaked = client.get(f"/_ops?token={token}")
            assert leaked.status_code == 401
    finally:
        _clear_admin_env()
