"""Synthetic demo seed/purge against a live test database."""

from __future__ import annotations

import pytest
from rich.console import Console
from sqlalchemy import func, select

pytestmark = pytest.mark.usefixtures("seeded_db")


def test_purge_demo_removes_synthetic_then_reseed():
    from bib.db import models as m
    from bib.db.session import session_scope
    from bib.ingest.synthetic import purge_demo, seed_demo

    quiet = Console(quiet=True)
    try:
        purge_demo(console=quiet)
        with session_scope() as session:
            n_pop = session.scalar(
                select(func.count()).select_from(m.Population).where(m.Population.is_synthetic)
            )
            n_rel = session.scalar(
                select(func.count()).select_from(m.Release).where(m.Release.version == "demo")
            )
        assert n_pop == 0
        assert n_rel == 0
    finally:
        seed_demo(force=False, console=quiet)
        with session_scope() as session:
            n_pop = session.scalar(
                select(func.count()).select_from(m.Population).where(m.Population.is_synthetic)
            )
        assert n_pop > 0
