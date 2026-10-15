"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from bib.config import get_settings


def wait_for_database(*, timeout: float = 45, console=None) -> None:
    """Block until PostgreSQL accepts connections.

    ``bib serve`` calls this so a missing local container fails with a hint
    instead of a uvicorn traceback on the first request.
    """
    from time import monotonic, sleep

    from sqlalchemy import create_engine, text

    settings = get_settings()
    url = settings.database_url
    safe = url
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        safe = f"{scheme}://***@{rest.split('@', 1)[1]}"
    deadline = monotonic() + timeout
    last: Exception | None = None
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 2})
    try:
        while monotonic() < deadline:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                if console:
                    console.print(f"database: [green]reachable[/green] ({safe})")
                return
            except Exception as exc:
                last = exc
                sleep(0.4)
    finally:
        engine.dispose()
    hint = ""
    if ":5433" in url:
        hint = " Start the local box with: podman start bib-pg"
    raise SystemExit(f"database not reachable ({safe}): {last}.{hint}")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts/CLI: commit on success, rollback on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    with get_sessionmaker()() as session:
        yield session
