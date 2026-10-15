"""Structured request logs plus an in-process WARNING+ ring."""

from __future__ import annotations

import json
import logging
import sys
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from bib.config import Settings

_EXTRA_KEYS = ("request_id", "method", "path", "status", "duration_ms")


class LogRing:
    """Newest-first ring of WARNING+ records for the operator page."""

    def __init__(self, size: int = 200) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._buf.appendleft(item)

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._buf)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _EXTRA_KEYS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RingHandler(logging.Handler):
    def __init__(self, ring: LogRing) -> None:
        super().__init__(level=logging.WARNING)
        self.ring = ring

    def emit(self, record: logging.LogRecord) -> None:
        item: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key in _EXTRA_KEYS:
            if hasattr(record, key):
                item[key] = getattr(record, key)
        self.ring.add(item)


def setup_logging(settings: Settings, ring: LogRing) -> logging.Logger:
    logger = logging.getLogger("bib")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    stream = logging.StreamHandler(sys.stderr)
    if settings.should_log_json:
        stream.setFormatter(JsonFormatter())
    else:
        stream.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(stream)
    logger.addHandler(RingHandler(ring))
    logger.propagate = False
    return logger
