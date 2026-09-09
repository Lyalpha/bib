"""Test configuration.

The test database URL is resolved, in priority order, from:

1. ``BIB_TEST_DATABASE_URL``
2. ``DATABASE_URL``            (CI provides a ready-made ``bib_test`` database)
3. the dev default             ``postgresql+psycopg://bib:bib@localhost:5433/bib_test``

The chosen URL is pinned into the environment *before* any ``bib`` import so
the lru-cached settings and engine pick it up. Tests that need the database
are skipped automatically when no PostgreSQL server is reachable; if the
server is up but the test database is missing, it is created on the fly.
"""

from __future__ import annotations

import os

_TEST_URL = (
    os.environ.get("BIB_TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql+psycopg://bib:bib@localhost:5433/bib_test"
)
os.environ["BIB_DATABASE_URL"] = _TEST_URL

import pytest  # noqa: E402


def _database_skip_reason() -> str | None:
    """Return None when the test database is usable, else a skip reason."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(_TEST_URL)
    connect_args = {"connect_timeout": 2}
    try:
        with create_engine(_TEST_URL, connect_args=connect_args).connect():
            return None
    except Exception as exc:
        if "does not exist" not in str(exc):
            return f"postgres not reachable at {url.host}:{url.port} ({exc.__class__.__name__})"

    # Server is up but the database is missing — create it via an admin DB.
    for admin_db in ("postgres", "bib"):
        try:
            admin_url = url.set(database=admin_db).render_as_string(hide_password=False)
            engine = create_engine(
                admin_url, isolation_level="AUTOCOMMIT", connect_args=connect_args
            )
            with engine.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
            return None
        except Exception:
            continue
    return f"could not create test database {url.database!r}"


@pytest.fixture(scope="session")
def seeded_db() -> None:
    """Migrate the test database to head and seed the synthetic demo dataset."""
    reason = _database_skip_reason()
    if reason:
        pytest.skip(reason)

    from rich.console import Console

    from bib.db.bootstrap import init_database
    from bib.ingest.synthetic import seed_demo

    quiet = Console(quiet=True)
    init_database(console=quiet)
    seed_demo(force=False, console=quiet)


@pytest.fixture(scope="session")
def client():
    """App test client. Pages render even without a database."""
    from fastapi.testclient import TestClient

    from bib.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def api_client(seeded_db, client):
    """Test client guaranteed to sit on a migrated, demo-seeded database."""
    return client
