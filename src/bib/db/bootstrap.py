"""Database bootstrap: migrations, filter loading, status reporting."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from bib.config import get_settings

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config():
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def init_database(console: Console | None = None) -> None:
    """Upgrade the schema to head, then load bundled filters (idempotent)."""
    console = console or Console()
    from alembic import command

    console.print("[bold]bib init-db[/bold]")
    command.upgrade(alembic_config(), "head")
    console.print("  schema: [green]up to date[/green]")

    try:
        from bib.science.filters import load_bundled_filters

        added, total = load_bundled_filters()
        console.print(f"  filters: [green]{total} available[/green] ({added} newly loaded)")
    except ImportError:
        console.print("  filters: [yellow]loader not available yet — skipped[/yellow]")
    except FileNotFoundError as exc:
        console.print(f"  filters: [yellow]skipped ({exc})[/yellow]")


def print_info(console: Console | None = None) -> None:
    """Show configuration and a summary of loaded data."""
    console = console or Console()
    from sqlalchemy import func, select

    from bib.db import models as m
    from bib.db.session import get_sessionmaker

    settings = get_settings()
    safe_url = settings.database_url
    if "@" in safe_url and "://" in safe_url:
        scheme, rest = safe_url.split("://", 1)
        safe_url = f"{scheme}://***@{rest.split('@', 1)[1]}"
    console.print(f"[bold]database[/bold]: {safe_url}")

    try:
        with get_sessionmaker()() as session:
            table = Table(title="Loaded data", title_justify="left")
            table.add_column("table")
            table.add_column("rows", justify="right")
            for model in (
                m.Release,
                m.Population,
                m.Sed,
                m.Colours,
                m.Ionizing,
                m.StarMass,
                m.SnRates,
                m.Yields,
                m.MLRatio,
                m.StarCounts,
                m.Filter,
            ):
                count = session.execute(select(func.count()).select_from(model)).scalar()
                table.add_row(model.__tablename__, str(count))
            console.print(table)

            synthetic = session.execute(
                select(func.count()).select_from(m.Population).where(m.Population.is_synthetic)
            ).scalar()
            if synthetic:
                console.print(
                    f"[yellow]{synthetic} population(s) are synthetic demo data — not for science.[/yellow]"
                )
    except Exception as exc:  # DB unreachable or schema missing
        console.print(f"[red]database not ready:[/red] {exc}")
