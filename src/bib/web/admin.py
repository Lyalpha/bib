"""Hidden operator console. Mounted only when BIB_ADMIN_TOKEN is set."""

from __future__ import annotations

import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from bib.api.v1.endpoints import health_payload, ready_payload
from bib.ops.sentry import ADMIN_COOKIE
from bib.web.templating import templates

router = APIRouter(include_in_schema=False)


def _settings(request: Request):
    return request.app.state.settings


def tokens_match(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided, expected)


def is_authorized(request: Request) -> bool:
    expected = _settings(request).admin_token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and tokens_match(auth[7:].strip(), expected):
        return True
    return tokens_match(request.cookies.get(ADMIN_COOKIE), expected)


def _cookie_kwargs(request: Request) -> dict:
    settings = _settings(request)
    return {
        "key": ADMIN_COOKIE,
        "httponly": True,
        "samesite": "strict",
        "path": settings.normalized_admin_path,
        "secure": request.url.scheme == "https",
    }


def _page(request: Request, *, mode: str, status_code: int = 200, error: str | None = None):
    visits: list = []
    if mode == "dashboard":
        try:
            from sqlalchemy import select

            from bib.db import models as m
            from bib.db.session import session_scope

            cutoff = date.today() - timedelta(days=14)
            with session_scope() as session:
                visits = list(
                    session.scalars(
                        select(m.SiteDailyStat)
                        .where(m.SiteDailyStat.day >= cutoff)
                        .order_by(m.SiteDailyStat.day.desc(), m.SiteDailyStat.path)
                    )
                )
        except Exception:
            visits = []
    ready, ready_status = ready_payload()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "mode": mode,
            "error": error,
            "health": health_payload(),
            "ready": ready,
            "ready_ok": ready_status == 200,
            "logs": request.app.state.log_ring.records(),
            "visits": visits,
            "admin_path": _settings(request).normalized_admin_path,
        },
        status_code=status_code,
    )


@router.get("/")
@router.get("")
async def dashboard(request: Request):
    if not is_authorized(request):
        return _page(request, mode="login", status_code=401)
    return _page(request, mode="dashboard")


@router.get("/login")
async def login_form(request: Request):
    if is_authorized(request):
        return RedirectResponse(
            _settings(request).normalized_admin_path, status_code=HTTP_303_SEE_OTHER
        )
    return _page(request, mode="login")


@router.post("/login")
async def login(request: Request, token: str = Form("")):
    settings = _settings(request)
    if not tokens_match(token, settings.admin_token):
        return _page(request, mode="login", status_code=401, error="Invalid token")
    response = RedirectResponse(settings.normalized_admin_path, status_code=HTTP_303_SEE_OTHER)
    response.set_cookie(value=settings.admin_token, **_cookie_kwargs(request))
    return response


@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(
        f"{_settings(request).normalized_admin_path}/login", status_code=HTTP_303_SEE_OTHER
    )
    kw = _cookie_kwargs(request)
    response.delete_cookie(
        ADMIN_COOKIE,
        path=kw["path"],
        secure=kw["secure"],
        httponly=True,
        samesite="strict",
    )
    return response
