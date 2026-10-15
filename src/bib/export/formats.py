"""Serialize an ExportTable to JSON, CSV, ECSV, or whitespace ASCII."""

from __future__ import annotations

import json
from io import StringIO

import numpy as np
import yaml
from fastapi.responses import JSONResponse, Response, StreamingResponse

from bib.export.catalog import EXPORT_FORMATS
from bib.export.table import ExportTable

_FORMAT_BY_KEY = {row["key"]: row for row in EXPORT_FORMATS}


def _cell(value, datatype: str) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not np.isfinite(value):
        return ""
    if datatype == "string":
        return str(value)
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f"{float(value):.8e}"


def _comment_block(table: ExportTable, extra: list[str] | None = None) -> list[str]:
    lines = [f"# {table.title}"]
    lines.extend(f"# {line}" for line in table.comments)
    if extra:
        lines.extend(extra)
    return lines


def render_csv(table: ExportTable) -> str:
    buf = StringIO()
    for line in _comment_block(table):
        buf.write(line + "\n")
    for col in table.columns:
        buf.write(f"# column {col.name} [{col.unit}] — {col.description}\n")
    buf.write(",".join(c.name for c in table.columns) + "\n")
    rows = zip(*(c.as_list() for c in table.columns), strict=True)
    for row in rows:
        buf.write(",".join(_cell(v, c.datatype) for v, c in zip(row, table.columns, strict=True)) + "\n")
    return buf.getvalue()


def render_ascii(table: ExportTable) -> str:
    buf = StringIO()
    for line in _comment_block(table):
        buf.write(line + "\n")
    for col in table.columns:
        buf.write(f"# column {col.name} [{col.unit}] — {col.description}\n")
    buf.write("# " + " ".join(c.name for c in table.columns) + "\n")
    rows = zip(*(c.as_list() for c in table.columns), strict=True)
    for row in rows:
        buf.write(" ".join(_cell(v, c.datatype) for v, c in zip(row, table.columns, strict=True)) + "\n")
    return buf.getvalue()


def render_ecsv(table: ExportTable) -> str:
    datatype = [
        {
            "name": c.name,
            "unit": c.unit,
            "datatype": "string" if c.datatype == "string" else "float64",
            "description": c.description,
        }
        for c in table.columns
    ]
    header = {
        "delimiter": ",",
        "datatype": datatype,
        "meta": table.meta,
        "schema": "astropy-2.0",
    }
    dumped = yaml.safe_dump(header, sort_keys=False, allow_unicode=True).rstrip()
    buf = StringIO()
    buf.write("# %ECSV 1.0\n")
    buf.write("# ---\n")
    for line in dumped.splitlines():
        buf.write(f"# {line}\n")
    for line in _comment_block(table):
        buf.write(line + "\n")
    buf.write(",".join(c.name for c in table.columns) + "\n")
    rows = zip(*(c.as_list() for c in table.columns), strict=True)
    for row in rows:
        buf.write(",".join(_cell(v, c.datatype) for v, c in zip(row, table.columns, strict=True)) + "\n")
    return buf.getvalue()


def render_json(table: ExportTable) -> dict:
    return {
        "meta": table.meta,
        "title": table.title,
        "comments": table.comments,
        "columns": table.column_records(),
        "n_rows": table.n_rows,
        "data": {c.name: c.as_list() for c in table.columns},
    }


def render_export(table: ExportTable, fmt: str) -> Response:
    spec = _FORMAT_BY_KEY[fmt]
    disposition = f'attachment; filename="{table.filename}"'
    if fmt == "json":
        return JSONResponse(render_json(table), headers={"Content-Disposition": disposition})
    if fmt == "csv":
        body = render_csv(table)
    elif fmt == "ecsv":
        body = render_ecsv(table)
    else:
        body = render_ascii(table)
    return StreamingResponse(
        iter([body]),
        media_type=spec["media"],
        headers={"Content-Disposition": disposition},
    )
