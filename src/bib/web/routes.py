"""HTML page routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bib.web.templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/tutorial")
async def tutorial(request: Request):
    return templates.TemplateResponse(request, "tutorial.html")


@router.get("/sed")
async def sed_explorer(request: Request):
    return templates.TemplateResponse(request, "sed.html")


@router.get("/hr")
async def hr_explorer(request: Request):
    return templates.TemplateResponse(request, "hr.html")


@router.get("/data")
async def data_page(request: Request):
    return templates.TemplateResponse(request, "data.html")


@router.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html")
