# bib — BPASS-in-Browser

**bib** is a pedagogy-first web interface to the publicly released
[BPASS](https://bpass.auckland.ac.nz) (Binary Population and Spectral Synthesis)
data products: interactive SEDs of simple stellar populations, synthetic AB
photometry through bundled or user-supplied filters, and dust extinction of the SED.

It is for quick-look analysis and data-fetching of specific populations'
data through the API. For scripted or large-scale analysis, use
[hoki](https://heloises.github.io/hoki/intro.html) and the BPASS manuals and
release papers. BPASS data are licensed
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) by the BPASS team
(J. J. Eldridge & E. R. Stanway); bib itself is MIT.

## Quickstart — containers

```sh
podman compose up --build     # or: docker compose up --build
```

Open <http://localhost:8000>. The first start migrates the schema and seeds the
clearly-labelled **synthetic demo dataset** so there is something to play with
immediately.

## Quickstart — bare metal

Requires [uv](https://docs.astral.sh/uv/) and PostgreSQL 16+:

```sh
uv sync
export DATABASE_URL="postgresql+psycopg://bib:bib@localhost:5432/bib"
uv run bib init-db
uv run bib demo-seed
uv run bib serve
```

On an unprivileged VM use `scripts/deploy-vm.sh --host your.server.example`
(systemd --user, gunicorn on loopback, Apache `.htaccess` `[P]`). See
[Operations](operations.md).

## The CLI

| Command | Purpose |
|---|---|
| `bib init-db` | Create/upgrade the schema (Alembic) and load bundled filter curves |
| `bib demo-seed` | Load the synthetic demo dataset (`--force` to reseed, `--remove` to delete it) |
| `bib ingest --source DIR` | Ingest real BPASS files per a manifest ([guide](ingestion.md)). Operators only — not shown on the public Data & API page. SED loads: `sed-100.yaml` (v2.2.1, 100 M☉), `sed-extra-imfs.yaml` (the other v2.2.1 IMFs), and `sed-v23.yaml` (v2.3 alpha packs). |
| `bib serve` | Run the web app (`--reload` for development) |
| `bib down` | Stop a running `bib serve` (leaves PostgreSQL / `bib-pg` alone) |
| `bib info` | Show configuration and per-table row counts |

## Acknowledging BPASS

If anything produced with this tool ends up in a paper, talk or classroom,
include the official acknowledgement (shown, with copy buttons, on the landing
page) and cite Eldridge, Stanway et al. (2017), Stanway & Eldridge (2018) and —
for the alpha-enhanced grids — Byrne et al. (2022).
