"""HTML page routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from bib.web.templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/")
@router.get("/index.html")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/tutorial")
async def tutorial(request: Request):
    return templates.TemplateResponse(request, "tutorial.html")


@router.get("/ssp")
async def ssp_explorer(request: Request):
    return templates.TemplateResponse(request, "sed.html")


@router.get("/sed")
async def sed_explorer_redirect():
    return RedirectResponse("/ssp", status_code=301)


@router.get("/request")
async def request_data_page(request: Request):
    return templates.TemplateResponse(request, "request.html")


@router.get("/data")
async def data_page(request: Request):
    return templates.TemplateResponse(request, "data.html")


@router.get("/about")
async def about_redirect():
    return RedirectResponse("/#acknowledgement", status_code=301)


@router.get("/privacy")
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html")
