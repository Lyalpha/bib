"""Serialize an ExportTable to JSON, CSV, ECSV, or whitespace ASCII."""

from __future__ import annotations

from collections.abc import Iterator

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


def _column_comments(table: ExportTable) -> Iterator[str]:
    for col in table.columns:
        yield f"# column {col.name} [{col.unit}] — {col.description}\n"


def _rows(table: ExportTable, sep: str) -> Iterator[str]:
    """Yield one serialised data row at a time (no full-table string in memory)."""
    columns = table.columns
    lists = [c.as_list() for c in columns]
    for row in zip(*lists, strict=True):
        yield sep.join(_cell(v, c.datatype) for v, c in zip(row, columns, strict=True)) + "\n"


def iter_csv(table: ExportTable) -> Iterator[str]:
    for line in _comment_block(table):
        yield line + "\n"
    yield from _column_comments(table)
    yield ",".join(c.name for c in table.columns) + "\n"
    yield from _rows(table, ",")


def iter_ascii(table: ExportTable) -> Iterator[str]:
    for line in _comment_block(table):
        yield line + "\n"
    yield from _column_comments(table)
    yield "# " + " ".join(c.name for c in table.columns) + "\n"
    yield from _rows(table, " ")


def iter_ecsv(table: ExportTable) -> Iterator[str]:
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
    yield "# %ECSV 1.0\n"
    yield "# ---\n"
    for line in dumped.splitlines():
        yield f"# {line}\n"
    for line in _comment_block(table):
        yield line + "\n"
    yield ",".join(c.name for c in table.columns) + "\n"
    yield from _rows(table, ",")


def render_csv(table: ExportTable) -> str:
    return "".join(iter_csv(table))


def render_ascii(table: ExportTable) -> str:
    return "".join(iter_ascii(table))


def render_ecsv(table: ExportTable) -> str:
    return "".join(iter_ecsv(table))


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
        body = iter_csv(table)
    elif fmt == "ecsv":
        body = iter_ecsv(table)
    else:
        body = iter_ascii(table)
    # Streamed line by line: large SED tables never exist as one string in memory.
    return StreamingResponse(
        body,
        media_type=spec["media"],
        headers={"Content-Disposition": disposition},
    )
