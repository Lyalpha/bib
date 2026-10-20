# Operations

Notes for running bib as a **public pedagogical site** (university Linux host
behind Apache or Caddy, or a compose stack with credentials changed). This is
not a full observability platform: logs go to stderr/journald, probes are two
HTTP endpoints, and visit counts are first-party path totals.

For branding, bind address, and the base env table see
[Branding & deployment](deployment.md).

## Bind locally; proxy in front

`bib serve` defaults to `0.0.0.0:8000`. On a public host bind loopback and
terminate TLS at the reverse proxy:

```sh
export BIB_HOST=127.0.0.1
uv run bib serve --host 127.0.0.1 --port 8000
```

`bib serve` always enables uvicorn `proxy_headers=True` so `X-Forwarded-For`
and `X-Forwarded-Proto` from a **trusted** proxy set the client IP (used by
the in-process rate limiter) and HTTPS detection (used for the operator
cookie's `Secure` flag).

`BIB_FORWARDED_ALLOW_IPS` (default `127.0.0.1`) is the uvicorn
`forwarded_allow_ips` list: comma-separated addresses of proxies whose
forwarded headers bib may trust. Leave the default when Apache or Caddy
runs on the same machine. If the proxy is elsewhere, set that proxy's IP —
do not use `*` on a host that also accepts untrusted traffic.

Optional `BIB_ALLOWED_HOSTS` is a comma-separated Host allowlist
(Starlette `TrustedHostMiddleware`). Empty means the middleware is not
installed.

## Unprivileged host (systemd --user)

No root required. PostgreSQL must already be running on the box; bib binds
loopback and expects a reverse proxy in front.

`scripts/deploy-vm.sh` is the install path:

```sh
./scripts/deploy-vm.sh --host your.server.example --demo-seed
```

That rsyncs this checkout to `~/bib` on the server (see `deploy/rsync-exclude`),
installs [uv](https://docs.astral.sh/uv/) in the user prefix if missing,
creates a PostgreSQL database **owned by a new role** `bib_app`, writes
`~/.config/bib/env`, runs `uv sync --frozen` + `bib init-db`, and enables
`~/.config/systemd/user/bib.service`. Re-run the same command to ship
code updates; the DSN is reused unless you pass `--reset-app-password`.

Rsync only (no uv, database, systemd, or `.htaccess`):

```sh
./scripts/deploy-vm.sh --host your.server.example --sync-only
```

Once `~/bib` is a git clone, ship code with a fast-forward pull instead of
rsync (`.env` and `~/.config/bib/env` stay outside the checkout):

```sh
cd ~/bib
git pull --ff-only
uv sync --frozen --python 3.13 --extra prod
uv run --frozen --extra prod bib init-db
systemctl --user restart bib
```

Gunicorn keeps the previous tree in memory until `systemctl --user restart bib`.

A privileged PostgreSQL role (`postgres` by default, `--db-admin-user`,
`BIB_DB_ADMIN_USER`, or that key in the checkout `.env`) is used **once**
to create `bib_app`. The deploy script does **not** load the rest of `.env`
(your local `BIB_DATABASE_URL` must not reach the server). `.env` is
rsync-excluded. The admin password is prompted (or
`BIB_DB_ADMIN_PASSWORD`) and **not stored**. The app DSN in
`~/.config/bib/env` is the application role only. Do not put admin
credentials in the unit file.

If the OS user cannot write system unit files, lingering must be on so the
user unit survives logout (`loginctl enable-linger`). The script tries to
enable it.

Gunicorn (extra `prod`) binds **loopback port 8001**. Apache in front is
usually already serving the document root; the deploy script **copies**
`deploy/htaccess.example` to `/var/www/html/.htaccess` (never `mv` from
`$HOME` — that keeps the wrong SELinux type and Apache 403s). The rule is a
server-side proxy (`RewriteRule … [P]`), not a client redirect to localhost.

If that `.htaccess` 500s, `AllowOverride` does not permit `[P]`: fall back to
`deploy/httpd-bib.conf.example` in the TLS vhost (that may need whoever
manages httpd). Until Apache is proxying:

```sh
ssh your.server.example 'curl -sS http://127.0.0.1:8001/api/v1/health'
ssh your.server.example 'journalctl --user -u bib -f'
```

Real BPASS products are not in git. After the unit is up, `--ingest` is a
path **on the server**:

```sh
./scripts/deploy-vm.sh --host your.server.example --ingest /path/on/the/server/to/bpass
```

Desktop access to Postgres should be an SSH tunnel to `localhost:5432`, not
a published database port.

Hosts with a system Apache they cannot fully configure still use this path:
gunicorn on loopback, `.htaccess` `[P]` proxy if allowed, otherwise the
vhost fragment.

## systemd (root / dedicated host)

Logs on stderr become journald. Keep the process on loopback:

```ini
[Unit]
Description=bib BPASS-in-Browser
After=network.target postgresql.service

[Service]
Type=simple
User=bib
Group=bib
WorkingDirectory=/srv/bib
EnvironmentFile=/etc/bib.env
ExecStart=/usr/bin/uv run --frozen bib serve --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`/etc/bib.env` should set `BIB_DATABASE_URL` (or `DATABASE_URL`), a strong
`BIB_ADMIN_TOKEN` if you want the operator console, and any other `BIB_*`
overrides. Do not put secrets in the unit file. Without root, use the user
unit in `deploy/bib.user.service` instead (`scripts/deploy-vm.sh`).

## Apache

Cap the request body **above** bib's 1 MiB custom-filter upload limit so
multipart overhead still fits; `2 MiB` is enough. The app itself rejects
larger filter files with HTTP 413.

```apache
<VirtualHost *:443>
    ServerName bib.example.ac.uk
    SSLEngine on
    # SSLCertificateFile / SSLCertificateKeyFile …

    LimitRequestBody 2097152

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/
</VirtualHost>
```

## Caddy

```caddy
bib.example.ac.uk {
    request_body {
        max_size 2MB
    }
    reverse_proxy 127.0.0.1:8000
}
```

Caddy sets forwarded headers for `reverse_proxy`. Keep
`BIB_FORWARDED_ALLOW_IPS` pointed at the proxy.

## Probes

| endpoint | role | behaviour |
|---|---|---|
| `GET /api/v1/health` | liveness | No database. `{"status":"ok","version":"…"}`. |
| `GET /api/v1/ready` | readiness | Runs `SELECT 1`. `{"status":"ok"}` or **503** `{"status":"unavailable"}` (no DSN or SQL in the body). |

Point the hypervisor or proxy at **health** for “is the process up?” and
**ready** for “can it serve after a DB blip?”. There is no Kubernetes
manifest in this repo.

## Logs and error reporting

When `BIB_DEBUG` is false, request logs are **JSON lines on stderr**
(`BIB_LOG_JSON` overrides: unset follows debug, `true`/`false` force the
format). Each request (except `/static`) includes `request_id`, `method`,
`path`, `status`, `duration_ms`. WARNING and above also go into an
in-process ring of the last ~200 records, shown on the operator console.

Ship those lines with journald or a reverse-proxy access log. Hosted drains
(Better Stack, Axiom, and similar) are **optional and not wired** — scrape
stderr yourself if you want them.

Optional [Sentry](https://sentry.io/)-compatible reporting
([GlitchTip](https://glitchtip.com/) works with the same DSN):

```sh
uv sync --extra ops          # from a checkout; extra is sentry-sdk[fastapi]
# or: uv pip install 'bib[ops]'
export BIB_SENTRY_DSN="https://…@…"
```

`sentry-sdk` is not a required dependency. If the DSN is set but the extra
is missing, bib logs a warning and continues. Events are sent with
`send_default_pii=False`, no request bodies, and Authorization / admin
cookie values scrubbed. After a restart you should see `Sentry error
reporting enabled` in the logs. `uv run bib sentry-ping` sends a test
exception.

With a DSN, each non-static request also emits Sentry metrics (look under
**Metrics** in the Sentry project):

| metric | type | attributes |
|---|---|---|
| `bib.request` | counter | `route`, `method`, `status` (`2xx` / `4xx` / `5xx`) |
| `bib.request.duration` | distribution (ms) | same |
| `bib.ratelimit` | counter | when a 429 is served |
| `bib.page_hit` | counter | allowlisted HTML paths only |

`route` is collapsed (`/ssp`, `api`, `admin`, `other`) so population IDs
never become metric series. Set `BIB_SENTRY_ENVIRONMENT` (or
`SENTRY_ENVIRONMENT`) to keep local traffic out of the production view;
unset, it is `production` unless `BIB_DEBUG` is on. GlitchTip may ignore
these metrics; Sentry SaaS is the intended sink.

Sentry Issues and Metrics are **not** an uptime check. A dead process, a
wedged uvicorn, or a down Postgres sends nothing. On the public VM:

- run `bib serve` under systemd (`Restart=on-failure`)
- add [Sentry Uptime](https://docs.sentry.io/product/alerts/uptime-monitoring/)
  (or any external ping) against `GET /api/v1/health` and `GET /api/v1/ready`
- set `BIB_SENTRY_ENVIRONMENT=production` on that host so laptop traffic
  does not mix with the live series

Unhandled Python exceptions still go to Issues. Browser / Plotly errors do
not. There are no alert rules in this repo — create them in the Sentry
project (5xx rate, uptime, a spike in `bib.ratelimit`).

## Operator console

Set `BIB_ADMIN_TOKEN` to a long random secret **or leave it empty**. If the
token is unset, the console routes are **not registered**: the path 404s
like any missing page and does not advertise itself.

`BIB_ADMIN_PATH` defaults to `/_ops` (rejected values such as `/` or
`/api` fall back to that default). Treat the path as unlisted: do not put
it in the public nav, footer, sitemap, or OpenAPI. `/robots.txt` is
generated in-process and **never names the operator path** (it only
disallows `/api/docs` and `/api/redoc`).

Auth is `Authorization: Bearer <token>` or a small login form that sets an
HttpOnly, SameSite=Strict cookie (`bib_ops`) scoped to the admin path,
`Secure` when the request is HTTPS. The cookie stores a SHA-256 digest of
the token, not the token itself, so a leaked cookie cannot be replayed as a
Bearer token. The token is not accepted in the query string. After login the page shows liveness/readiness, the recent-error
ring, and 14 days of visit counts.

Obscurity is extra, not a substitute for the token.

## Privacy and visit counts

bib stores **date + path + hit count** only (`site_daily_stat`). No IP,
user-agent, fingerprint, query string, or cookies are recorded. Counts are
HTML **GET**s that return 2xx/3xx on an allowlist:

`/`, `/ssp`, `/tutorial`, `/data`, `/sed`

`/static`, `/api`, and the operator console are not counted. Totals flush
to PostgreSQL about every `BIB_STATS_FLUSH_SECONDS` (default 60) and on
shutdown; a missing table is logged and ignored.

This is not personal data under GDPR-style rules, so there is **no consent
banner**. Do not add third-party analytics (GA, Mixpanel, Plausible, Umami)
to a public bib; a future GoatCounter snippet is out of scope here.

## Schema and backups

`bib init-db` runs Alembic to **head**, which includes revision
`c3f8a1d0e6b2` (`site_daily_stat`: `day`, `path`, `hits`). Existing
databases need that upgrade before visit counts persist.

Logical backup is PostgreSQL's:

```sh
pg_dump -Fc -d bib -f bib-$(date -u +%Y%m%d).dump
# restore: pg_restore -d bib --clean --if-exists bib-YYYYMMDD.dump
```

Dump the database you actually serve (production DSN), not the compose
sandbox defaults. Filter CSVs and `branding.yaml` live on disk — include
them in host backups if you customized them.

## Compose sandbox vs public

`compose.yaml` is a **local sandbox**: database user/password `bib`/`bib`,
app DSN `postgresql+psycopg://bib:bib@db:5432/bib`. Change those before
any public deployment. The compose file does not publish PostgreSQL to the
host; **never** add a `5432:5432` (or equivalent) publish on a public
machine.

The in-memory rate limiter (default `BIB_RATE_LIMIT_PER_MINUTE=40`) covers
the expensive routes (`POST /api/v1/photometry`, `GET /api/v1/export`,
`/sed_frames`, the custom-SED upload and the operator login) and is
**per process**. It is fine for one or two uvicorn workers; it does not
sync across hosts. Export tables are streamed row by row, so a large
all-ages SED export never holds the whole file in memory.

Interactive OpenAPI (`/api/docs`, `/api/redoc`) is on by default. `/api` and
`/api/v1` redirect there. Set `BIB_EXPOSE_DOCS=false` to hide the Swagger UI.

## Releases and Zenodo

1. Fill the author placeholders in `CITATION.cff`, `.zenodo.json`,
   `pyproject.toml` and `LICENSE` (the release workflow refuses to run while
   any `<…>` remain).
2. Bump the version in `pyproject.toml`, `src/bib/__init__.py`,
   `CITATION.cff` and `.zenodo.json`; add a `## [x.y.z]` section to
   `CHANGELOG.md`; run `uv lock`.
3. Tag and push: `git tag -a vx.y.z -m "bib x.y.z" && git push --tags`.
   `release.yml` validates the metadata, publishes the image and creates the
   GitHub release with the changelog section as notes.
4. **Zenodo.** Enable the repository once at
   <https://zenodo.org/account/settings/github/>. Every GitHub release is
   then archived automatically; Zenodo reads `.zenodo.json` for creators,
   licence, keywords and the `related_identifiers` that cite the BPASS
   papers, and mints a version DOI plus a concept DOI. After the first
   release, paste the concept DOI into `CITATION.cff` (`identifiers:`) and
   the README badge so later versions resolve to the right record.
5. Re-run `science-regression.yml` (it also fires on the tag) and keep its
   summary with the release notes for an RNAAS-style companion paper.

## Rate limits and uploads

One in-process token bucket applies to custom-filter POST, `sed_frames`,
native/CSV SED downloads, GET photometry, `GET /api/v1/export`, and operator
login POST. Exceeding the limit returns **429** with `Retry-After: 60`. Custom
filter uploads are read in chunks and aborted at **1 MiB**; keep the
reverse-proxy body limit in the same ballpark (see Apache/Caddy above).
