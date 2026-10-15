"""bib command line interface.

Commands:
    bib init-db      Create/upgrade the database schema and load bundled filters.
    bib ingest       Ingest real BPASS data files according to a manifest.
    bib demo-seed    Load the synthetic demonstration dataset (``--remove`` to delete it).
    bib serve        Run the web application.
    bib down         Stop a running bib serve (leaves PostgreSQL alone).
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
    remove: bool = typer.Option(
        False, "--remove", help="Delete synthetic demo rows without reseeding."
    ),
) -> None:
    """Generate and load the synthetic demonstration dataset (clearly labelled, not for science)."""
    if remove and force:
        raise typer.BadParameter("use --remove or --force, not both")
    if remove:
        from bib.ingest.synthetic import purge_demo

        purge_demo(console=console)
        return
    from bib.ingest.synthetic import seed_demo

    seed_demo(force=force, console=console)


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind host (default from settings)."),
    port: int = typer.Option(None, help="Bind port (default from settings)."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (development)."),
) -> None:
    """Run the bib web server after checking that PostgreSQL is reachable."""
    import uvicorn

    from bib.config import get_settings
    from bib.db.session import wait_for_database

    settings = get_settings()
    wait_for_database(console=console)
    uvicorn.run(
        "bib.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


@app.command()
def down(
    port: int = typer.Option(None, help="Listen port to match (default from settings)."),
    timeout: float = typer.Option(8.0, help="Seconds to wait after SIGTERM before SIGKILL."),
) -> None:
    """Stop a running bib web server. Does not stop PostgreSQL or bib-pg."""
    from bib.config import get_settings
    from bib.down import find_server_pids, stop_pids

    settings = get_settings()
    target_port = port or settings.port
    pids = find_server_pids(target_port)
    if not pids:
        console.print(f"No bib server found (port {target_port}).")
        raise typer.Exit(0)
    console.print(f"Stopping bib server [bold]{', '.join(str(p) for p in sorted(pids))}[/bold] …")
    signaled, leftover = stop_pids(pids, timeout=timeout)
    if leftover:
        console.print(f"[red]Still running:[/red] {', '.join(str(p) for p in sorted(leftover))}")
        raise typer.Exit(1)
    if signaled:
        console.print("[green]Stopped.[/green] PostgreSQL was left running.")
    else:
        console.print("No process could be signaled (permission denied?).")
        raise typer.Exit(1)


@app.command()
def info() -> None:
    """Print configuration and a summary of what is loaded in the database."""
    from bib.db.bootstrap import print_info

    print_info(console=console)


@app.command("sentry-ping")
def sentry_ping() -> None:
    """Send a test exception to Sentry/GlitchTip (requires BIB_SENTRY_DSN and bib[ops])."""
    from bib.config import get_settings
    from bib.ops.sentry import init_sentry

    get_settings.cache_clear()
    settings = get_settings()
    if not (settings.sentry_dsn or "").strip():
        console.print("[red]No DSN[/red] — set BIB_SENTRY_DSN in the environment or .env")
        raise typer.Exit(1)
    init_sentry(settings)
    try:
        import sentry_sdk
    except ImportError:
        console.print("[red]sentry-sdk is not installed[/red] — run [bold]uv sync --extra ops[/bold]")
        raise typer.Exit(1) from None
    client = sentry_sdk.get_client()
    if not client.is_active():
        console.print("[red]Sentry client is not active[/red] after init — check the DSN")
        raise typer.Exit(1)
    try:
        raise RuntimeError("bib sentry-ping: intentional test error")
    except RuntimeError:
        event_id = sentry_sdk.capture_exception()
    sentry_sdk.flush(timeout=20)  # returns None on success
    if event_id:
        console.print(f"[green]Sent test event[/green] {event_id} — check the Sentry Issues stream.")
    else:
        console.print("[red]SDK did not accept the event[/red]")
        raise typer.Exit(1)


def main() -> None:  # console-script entry point
    app()


if __name__ == "__main__":
    main()
