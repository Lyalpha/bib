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

`compose.yaml` is a **sandbox**: user/password `bib`/`bib`. Change those
before a public deployment, and never publish PostgreSQL port 5432 to the
host. Public-release ops (systemd, reverse proxy, probes, admin token,
privacy) are in [Operations](operations.md).

## Bare metal

For environments where containers are not allowed:

```sh
uv sync --frozen
export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/bib"
uv run bib init-db
uv run bib demo-seed        # optional sandbox data
uv run bib serve
```

`bib serve` waits for PostgreSQL (about 45 s) and prints a `podman start bib-pg` hint if the local DSN is on port 5433. Raw uvicorn does not.

Any WSGI-less ASGI setup works too (`uvicorn 'bib.app:create_app' --factory`).

### Unprivileged VM (systemd --user)

`scripts/deploy-vm.sh` rsyncs the tree, creates a `bib_app` Postgres role via
a privileged admin role (`postgres` by default), installs a systemd **user**
unit running gunicorn on `127.0.0.1:8001`, and copies an Apache `.htaccess`
`RewriteRule [P]` into the document root. Details: [Operations](operations.md).

```sh
./scripts/deploy-vm.sh --host your.server.example --demo-seed
```

## Configuration

All settings are environment variables with the `BIB_` prefix (a plain
`DATABASE_URL` is also accepted). A `.env` file in the working directory is
read automatically. On a VM, `~/.config/bib/env` (written by `deploy-vm.sh`,
used by the systemd unit) is also read; a checkout `.env` overrides it.

| variable | default | purpose |
|---|---|---|
| `BIB_DATABASE_URL` / `DATABASE_URL` | `postgresql+psycopg://bib:bib@localhost:5432/bib` | PostgreSQL DSN (psycopg3 driver) |
| `BIB_HOST` / `BIB_PORT` | `0.0.0.0` / `8000` | bind address |
| `BIB_BRANDING_FILE` | — | path to a custom `branding.yaml` |
| `BIB_DEBUG` | `false` | FastAPI debug mode |
| `BIB_FILTERS_DIR` | bundled `data/filters` | filter curve directory |
| `BIB_ADMIN_TOKEN` | empty | shared operator-console secret; **unset ⇒ console routes are not registered (404)** |
| `BIB_ADMIN_PATH` | `/_ops` | unlisted operator-console path (do not advertise; never put it in `robots.txt`) |
| `BIB_SENTRY_DSN` | empty | optional Sentry/GlitchTip DSN; requires extra `bib[ops]` (`sentry-sdk`) |
| `BIB_SENTRY_ENVIRONMENT` | `production` (or `development` if `BIB_DEBUG`) | Sentry environment tag; `SENTRY_ENVIRONMENT` is also accepted |
| `BIB_ALLOWED_HOSTS` | empty | comma-separated Host allowlist; empty disables the middleware |
| `BIB_EXPOSE_DOCS` | unset (on) | `/api/docs` and `/api/redoc`; unset means exposed. Set `false` to hide. `/api` and `/api/v1` redirect to the docs when they are on. |
| `BIB_LOG_JSON` | unset | JSON request logs on stderr; unset means JSON when debug is false |
| `BIB_RATE_LIMIT_PER_MINUTE` | `40` | in-process token bucket for expensive routes (per process, not clustered) |
| `BIB_STATS_FLUSH_SECONDS` | `60` | how often allowlisted HTML hit counts flush to `site_daily_stat` |
| `BIB_FORWARDED_ALLOW_IPS` | `127.0.0.1` | uvicorn `forwarded_allow_ips`; IPs whose `X-Forwarded-*` headers are trusted |

## Branding

Everything visual that identifies a deployment lives in `branding.yaml`:
site name, full name, tagline, optional logo, optional public `source_url`
(the git remote — do not serve the live checkout from the app), footer note
and the full colour palette. The palette is injected as CSS custom properties
(`--brand-primary`, `--brand-bg`, …) which every stylesheet and plot uses — so
a deployment can be rebranded without touching the package:

```yaml
site_name: "starlab"
full_name: "StarLab Explorer"
tagline: "Our teaching instance."
logo: assets/starlab.svg
source_url: https://example.org/your/bib
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
are skipped automatically when no PostgreSQL server is reachable.

The workflows under `.github/workflows/` describe the intended CI/CD shape
(they run once the repository is mirrored to GitHub or an equivalent runner
is attached):

| workflow | trigger | what it does |
|---|---|---|
| `ci.yml` | push to `main`, pull requests | `uv lock --check`, ruff lint + format, `cffconvert --validate`, pytest against a PostgreSQL service (Python 3.13), `mkdocs build --strict`, container build + health probe |
| `science-regression.yml` | weekly, `v*` tags, manual | fetches the BPASS subset, runs `pytest -m realdata`, publishes the pass/fail table in the job summary |
| `release.yml` | `v*` tags | checks tag = `pyproject` = package = `CITATION.cff` = `.zenodo.json` and that no placeholders remain, pushes the image to GHCR, creates the GitHub release from the matching `CHANGELOG.md` section |
| `security.yml` | push, PR, weekly | `pip-audit` on the exported lock, `gitleaks` over history |

Dependabot (`.github/dependabot.yml`) opens monthly grouped updates for the
`uv` lock, GitHub Actions and the base image.
