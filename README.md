# bib — BPASS-in-Browser

**bib** is a pedagogical web interface for exploring [BPASS](https://bpass.auckland.ac.nz)
(Binary Population and Spectral Synthesis) results: interactive spectral energy
distributions of simple stellar populations, synthetic photometry in standard or
user-supplied filters, and dust extinction of the SED.

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
# later: uv run bib down    # stops the web process only, not Postgres
```

On a host where you cannot use containers or root systemd:

```sh
./scripts/deploy-vm.sh --host your.server.example --demo-seed
```

That uses PostgreSQL on the server (a `bib_app` role created via a privileged
admin role, never stored in the app env), gunicorn on loopback port 8001, and
an Apache `.htaccess` proxy. See `docs/operations.md`.

## Ingesting real BPASS data

A public instance should already have data loaded. This section is for
operators who want to host their own copy. bib never redistributes BPASS
files — download the releases yourself:

- [BPASS v2.2.1](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/v2p2/)
  — population synthesis + stellar models (primary release).
- [BPASS v2.3](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/bpassv2p3/)
  — alpha-enhanced spectral synthesis extension.
- [bpass.auckland.ac.nz](https://bpass.auckland.ac.nz) — project home.

The full releases are large (hundreds of GB with individual stellar models).
You only need the files named in your ingest manifest. Official IMF tarballs
(`bpass_v2.2.1_imf*.tar.gz`) can stay packed.

```sh
# create / upgrade the schema and load the bundled filter curves
uv run bib init-db

# instant sandbox without any downloads (adds the warning banner)
uv run bib demo-seed

# pedagogical SED grid: v2.2.1, 100 M☉ IMFs (imf135_100 + imf_chab100)
uv run bib ingest --source /path/to/bpass-downloads --manifest src/bib/ingest/sed-100.yaml

# larger curated subset (default if you omit --manifest)
uv run bib ingest --source /path/to/bpass-downloads

# what ended up in the database?
uv run bib info
```

Re-runs are idempotent; use `--replace` to force re-ingestion. See
`docs/ingestion.md` for manifests, file layout, and the usual 100 M☉ load.
Science notes (units, magnitude systems, dust laws, event heuristics) live
in `docs/science-notes.md`.

## Examples

`notebooks/jwst_cluster_mass.ipynb` fetches one old binary population from a
running bib instance, plots the SED, and estimates a minimum cluster mass in
a JWST filter at low redshift.

`notebooks/science_checks.ipynb` repeats mass scaling, foreground-screen dust
extinction, the redshift transform, and AB photometry with the same equations
and libraries the server uses.

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
BPASS team — see `LICENSE` and the acknowledgement on the home page.
