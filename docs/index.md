# bib — BPASS-in-Browser

**bib** is a pedagogy-first web interface to the publicly released
[BPASS](https://bpass.auckland.ac.nz) (Binary Population and Spectral Synthesis)
data products: interactive SEDs of simple stellar populations, synthetic AB
photometry through bundled or user-supplied filters, dust attenuation, and
animated Hertzsprung–Russell evolution of individual stellar models — including
a to-scale binary-system visualizer.

It is an independent interface, not an official BPASS product. BPASS data are
licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) by the
BPASS team (J. J. Eldridge & E. R. Stanway); bib itself is MIT.

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

## The CLI

| Command | Purpose |
|---|---|
| `bib init-db` | Create/upgrade the schema (Alembic) and load bundled filter curves |
| `bib demo-seed` | Load the synthetic demo dataset (`--force` to reseed) |
| `bib ingest --source DIR` | Ingest real BPASS files per a manifest ([guide](ingestion.md)) |
| `bib serve` | Run the web app (`--reload` for development) |
| `bib info` | Show configuration and per-table row counts |

## Acknowledging BPASS

If anything produced with this tool ends up in a paper, talk or classroom,
include the official acknowledgement (shown, with copy buttons, on the landing
page) and cite Eldridge, Stanway et al. (2017), Stanway & Eldridge (2018) and —
for the alpha-enhanced grids — Byrne et al. (2022).
