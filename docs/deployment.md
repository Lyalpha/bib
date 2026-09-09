# Branding & deployment

## Containers

`compose.yaml` starts PostgreSQL 16 and the app; the entrypoint waits for the
database, migrates, seeds the demo dataset and serves on port 8000. Both
Podman and Docker work:

```sh
podman compose up --build     # or: docker compose up --build
```

The `Containerfile` is multi-stage (uv-based build, slim runtime) and
Docker-compatible.

## Bare metal

For environments where containers are not allowed:

```sh
uv sync --frozen
export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/bib"
uv run bib init-db
uv run bib demo-seed        # optional sandbox data
uv run bib serve
```

Any WSGI-less ASGI setup works too (`uvicorn 'bib.app:create_app' --factory`).

## Configuration

All settings are environment variables with the `BIB_` prefix (a plain
`DATABASE_URL` is also accepted); a `.env` file in the working directory is
read automatically.

| variable | default | purpose |
|---|---|---|
| `BIB_DATABASE_URL` / `DATABASE_URL` | `postgresql+psycopg://bib:bib@localhost:5432/bib` | PostgreSQL DSN (psycopg3 driver) |
| `BIB_HOST` / `BIB_PORT` | `0.0.0.0` / `8000` | bind address |
| `BIB_BRANDING_FILE` | — | path to a custom `branding.yaml` |
| `BIB_DEBUG` | `false` | FastAPI debug mode |
| `BIB_FILTERS_DIR` | bundled `data/filters` | filter curve directory |

## Branding

Everything visual that identifies a deployment lives in `branding.yaml`:
site name, full name, tagline, optional logo, footer note and the full colour
palette. The palette is injected as CSS custom properties
(`--brand-primary`, `--brand-bg`, …) which every stylesheet and plot uses — so
a deployment can be rebranded without touching the package:

```yaml
site_name: "starlab"
full_name: "StarLab Explorer"
tagline: "Our teaching instance."
logo: assets/starlab.svg
colors:
  primary: "#7c4dff"
  accent: "#ffd166"
  bg: "#101014"
footer_note: "Hosted by the StarLab teaching group."
```

Point `BIB_BRANDING_FILE` at your copy (or place `branding.yaml` in the
working directory). Colours omitted from your file keep their defaults.

## Tests and CI

```sh
uv run ruff check .
uv run pytest            # DB-backed tests use bib_test, created on demand
uv run mkdocs serve      # this documentation
```

Tests resolve their database from `BIB_TEST_DATABASE_URL`, then
`DATABASE_URL`, then a local default (`…@localhost:5433/bib_test`); API tests
are skipped automatically when no PostgreSQL server is reachable. GitHub
Actions runs lint + tests against a service container and builds the image.
