# bib — BPASS-in-Browser

**bib** is a pedagogical web interface for exploring [BPASS](https://bpass.auckland.ac.nz)
(Binary Population and Spectral Synthesis) results: interactive spectral energy
distributions of simple stellar populations, synthetic photometry in standard or
user-supplied filters, dust attenuation, and animated Hertzsprung–Russell diagram
evolution of individual stellar models and binary pairs.

- Grounded in the **BPASS v2.2.1** data release, extended with the **v2.3**
  alpha-enhancement spectral grids.
- Backed by PostgreSQL for fast selection and filtering; served by FastAPI with a
  documented REST API (`/api/docs`) designed to grow into a generic query builder.
- Ships with a clearly-labelled **synthetic demo dataset** so you can explore the
  interface immediately, before ingesting real BPASS data.

> BPASS data are licensed by the BPASS team under
> [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). If you use
> results obtained through this tool, please include the BPASS acknowledgement
> shown on the landing page and cite the appropriate papers.

## Quickstart (containers)

Requires podman (or docker) with the compose plugin:

```sh
podman compose up --build     # or: docker compose up --build
```

Then open <http://localhost:8000>. The first start creates the schema and seeds
the synthetic demo dataset (banner shown until real data is ingested).

## Quickstart (bare metal)

Requires [uv](https://docs.astral.sh/uv/) and a reachable PostgreSQL 16+:

```sh
uv sync
export DATABASE_URL="postgresql+psycopg://bib:bib@localhost:5432/bib"
uv run bib init-db
uv run bib demo-seed
uv run bib serve
```

## Ingesting real BPASS data

Download the BPASS v2.2.1 (and optionally v2.3) products from the
[BPASS site](https://bpass.auckland.ac.nz) or the
[Warwick mirror](https://warwick.ac.uk/bpass) into a directory, then:

```sh
uv run bib ingest --source /path/to/bpass-downloads
```

The default manifest (`src/bib/ingest/golden.yaml`) ingests the curated "golden
subset" used for demonstrations; edit or supply your own with `--manifest`.
See `docs/` for the full ingestion guide, file layout expectations, and the
science notes (units, magnitude systems, dust laws, event heuristics).

## Development

```sh
uv sync
uv run ruff check .
uv run pytest
uv run bib serve --reload
```

Documentation sources live in `docs/` (`uv run mkdocs serve`).

## Licence

bib itself is MIT licensed. BPASS data remain licensed CC BY-NC 4.0 by the
BPASS team — see `LICENSE` and the in-app Data & Resources page.
