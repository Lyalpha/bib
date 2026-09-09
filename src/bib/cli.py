"""bib command line interface.

Commands:
    bib init-db      Create/upgrade the database schema and load bundled filters.
    bib ingest       Ingest real BPASS data files according to a manifest.
    bib demo-seed    Load the synthetic demonstration dataset.
    bib serve        Run the web application.
    bib info         Show configuration and database status.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich")
console = Console()


@app.command("init-db")
def init_db() -> None:
    """Create or upgrade the database schema, then load bundled filters."""
    from bib.db.bootstrap import init_database

    init_database(console=console)


@app.command()
def ingest(
    source: Path = typer.Option(..., "--source", "-s", help="Directory containing BPASS data files."),
    manifest: Path = typer.Option(None, "--manifest", "-m", help="Golden-subset manifest YAML (defaults to the bundled golden.yaml)."),
    replace: bool = typer.Option(False, "--replace", help="Re-ingest items that already exist."),
) -> None:
    """Ingest real BPASS data products listed in a manifest."""
    from bib.ingest.run import run_ingest

    run_ingest(source=source, manifest=manifest, replace=replace, console=console)


@app.command("demo-seed")
def demo_seed(
    force: bool = typer.Option(False, "--force", help="Reseed even if demo data already exists."),
) -> None:
    """Generate and load the synthetic demonstration dataset (clearly labelled, not for science)."""
    from bib.ingest.synthetic import seed_demo

    seed_demo(force=force, console=console)


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind host (default from settings)."),
    port: int = typer.Option(None, help="Bind port (default from settings)."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (development)."),
) -> None:
    """Run the bib web server."""
    import uvicorn

    from bib.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "bib.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@app.command()
def info() -> None:
    """Print configuration and a summary of what is loaded in the database."""
    from bib.db.bootstrap import print_info

    print_info(console=console)


def main() -> None:  # console-script entry point
    app()


if __name__ == "__main__":
    main()
