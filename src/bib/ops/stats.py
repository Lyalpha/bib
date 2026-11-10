"""Allowlisted daily path counts (no IP, UA, query string, or cookies)."""

from __future__ import annotations

import asyncio
import datetime
import logging
import threading
from collections import Counter

from starlette.requests import Request
from starlette.responses import Response

COUNTED_PATHS = frozenset(
    {"/", "/ssp", "/tutorial", "/request", "/data", "/sed", "/privacy"}
)

log = logging.getLogger("bib.ops.stats")


def should_count(path: str, method: str) -> bool:
    return method == "GET" and path in COUNTED_PATHS


class PathCounter:
    def __init__(self) -> None:
        self._counts: Counter[tuple[datetime.date, str]] = Counter()
        self._lock = threading.Lock()

    def record(self, path: str) -> None:
        key = (datetime.date.today(), path)
        with self._lock:
            self._counts[key] += 1

    def snapshot(self) -> dict[tuple[datetime.date, str], int]:
        with self._lock:
            return dict(self._counts)

    def drain(self) -> dict[tuple[datetime.date, str], int]:
        with self._lock:
            items = dict(self._counts)
            self._counts.clear()
            return items

    def merge(self, items: dict[tuple[datetime.date, str], int]) -> None:
        with self._lock:
            self._counts.update(items)


def maybe_record(request: Request, response: Response) -> None:
    if response.status_code >= 400:
        return
    path = request.url.path
    if not should_count(path, request.method):
        return
    request.app.state.stats.record(path)
    from bib.ops.metrics import emit_page_hit

    emit_page_hit(path)


def flush_stats(app) -> None:
    pending = app.state.stats.drain()
    if not pending:
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from bib.db import models as m
        from bib.db.session import session_scope

        with session_scope() as session:
            for (day, path), n in pending.items():
                stmt = pg_insert(m.SiteDailyStat).values(day=day, path=path, hits=n)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_site_daily_stat_day_path",
                    set_={"hits": m.SiteDailyStat.hits + stmt.excluded.hits},
                )
                session.execute(stmt)
    except Exception as exc:
        log.warning("stats flush failed: %s", exc.__class__.__name__)
        app.state.stats.merge(pending)


def start_flusher(app) -> asyncio.Task:
    interval = max(5, int(app.state.settings.stats_flush_seconds))

    async def _loop() -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                flush_stats(app)
        except asyncio.CancelledError:
            flush_stats(app)
            raise

    return asyncio.create_task(_loop())
