#!/usr/bin/env bash
# Bare-metal deploy for a public bib instance (no containers).
#
# From a checkout, rsync to a host then configure it:
#
#   ./scripts/deploy-vm.sh --host your.server.example --demo-seed
#
# Or run on the server after the tree is in ~/bib:
#
#   ./scripts/deploy-vm.sh --demo-seed
#
# The script:
#   - rsyncs this checkout to $HOST:~/bib (when --host is set)
#   - installs uv in the user prefix if needed
#   - creates a PostgreSQL role+database via a privileged admin role
#     (never used by the running app)
#   - writes ~/.config/bib/env (application DSN only)
#   - uv sync --frozen, bib init-db, optional demo-seed / ingest
#   - installs a systemd *user* unit (gunicorn on loopback) and lingering
#   - copies deploy/htaccess.example to the Apache document root (copy, not mv)
#
# Apache .htaccess RewriteRule [P] proxies to gunicorn. If [P] is forbidden,
# use deploy/httpd-bib.conf.example in the TLS vhost instead.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy-vm.sh [options]

  --host HOST            SSH target. Rsync then run remotely.
  --remote-dir DIR       Remote/local install directory relative to \$HOME
                         (default: bib).
  --sync-only            With --host, rsync and exit (no uv, database,
                         systemd, or .htaccess).
  --no-sync              With --host, skip rsync (only run the remote script).
  --demo-seed            Load synthetic demo data after init-db.
  --ingest DIR           Ingest BPASS files from DIR (sed-100 manifest).
                         DIR is on the server, not the laptop.
  --skip-db              Do not create/alter PostgreSQL roles.
  --skip-unit            Do not install or restart the systemd user unit.
  --skip-htaccess        Do not copy .htaccess into the Apache document root.
  --reset-app-password   Recreate the application role password.
  --port N               Loopback port for gunicorn (default 8001).
  --docroot DIR          Apache document root for .htaccess (default
                         /var/www/html).
  --db-name NAME         Database name (default bib).
  --db-app-user NAME     Application role (default bib_app). Must not be the
                         admin role.
  --db-admin-user NAME   Privileged PostgreSQL role used only to create the
                         app role (default: postgres, or BIB_DB_ADMIN_USER).
  --public-host NAME     Host allowlist (default: hostname -f).
  -h, --help             Show this help.

Environment:
  BIB_DB_ADMIN_USER       Default for --db-admin-user. Also read from the
                          checkout .env (this key only; .env is not rsynced).
  BIB_DB_ADMIN_PASSWORD   Password for that admin role (prompted if unset and
                          a TTY is available; omit if peer/ident auth works).
                          Also read from checkout .env. Never written to
                          ~/.config/bib/env.
EOF
}

HOST=""
REMOTE_DIR="bib"
SYNC=1
SYNC_ONLY=0
DEMO_SEED=0
INGEST_DIR=""
SKIP_DB=0
SKIP_UNIT=0
SKIP_HTACCESS=0
RESET_APP_PASSWORD=0
PORT=8001
DOCROOT="/var/www/html"
DB_NAME="bib"
DB_APP_USER="bib_app"
DB_ADMIN_USER=""
PUBLIC_HOST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="${2:?}" ; shift 2 ;;
    --remote-dir) REMOTE_DIR="${2:?}" ; shift 2 ;;
    --sync-only) SYNC_ONLY=1 ; shift ;;
    --no-sync) SYNC=0 ; shift ;;
    --demo-seed) DEMO_SEED=1 ; shift ;;
    --ingest) INGEST_DIR="${2:?}" ; shift 2 ;;
    --skip-db) SKIP_DB=1 ; shift ;;
    --skip-unit) SKIP_UNIT=1 ; shift ;;
    --skip-htaccess) SKIP_HTACCESS=1 ; shift ;;
    --reset-app-password) RESET_APP_PASSWORD=1 ; shift ;;
    --port) PORT="${2:?}" ; shift 2 ;;
    --docroot) DOCROOT="${2:?}" ; shift 2 ;;
    --db-name) DB_NAME="${2:?}" ; shift 2 ;;
    --db-app-user) DB_APP_USER="${2:?}" ; shift 2 ;;
    --db-admin-user) DB_ADMIN_USER="${2:?}" ; shift 2 ;;
    --public-host) PUBLIC_HOST="${2:?}" ; shift 2 ;;
    -h|--help) usage ; exit 0 ;;
    *) echo "unknown argument: $1" >&2 ; usage >&2 ; exit 2 ;;
  esac
done

ident() {
  [[ "$1" =~ ^[a-z][a-z0-9_]{0,62}$ ]]
}

remote_dir_ok() {
  [[ "$1" =~ ^[A-Za-z0-9._][A-Za-z0-9._/-]*$ ]] && [[ "$1" != /* ]] && [[ "$1" != *..* ]]
}

# Checkout .env is for local app settings and is not rsynced. Pick up only
# deploy admin keys, and never override a real environment variable.
load_deploy_dotenv() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    case "$key" in
      BIB_DB_ADMIN_USER|BIB_DB_ADMIN_PASSWORD) ;;
      *) continue ;;
    esac
    [[ -n "${!key:-}" ]] && continue
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    if [[ "$val" == \"*\" && "$val" == *\" ]]; then
      val="${val#\"}"
      val="${val%\"}"
    elif [[ "$val" == \'*\' && "$val" == *\' ]]; then
      val="${val#\'}"
      val="${val%\'}"
    fi
    export "$key=$val"
  done < "$file"
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
load_deploy_dotenv "$ROOT/.env"
if [[ -z "$DB_ADMIN_USER" ]]; then
  DB_ADMIN_USER="${BIB_DB_ADMIN_USER:-postgres}"
fi
if ! ident "$DB_NAME" || ! ident "$DB_APP_USER" || ! ident "$DB_ADMIN_USER"; then
  echo "database/role names must be lowercase identifiers (got '$DB_NAME' / '$DB_APP_USER' / '$DB_ADMIN_USER')" >&2
  exit 2
fi
if [[ "$DB_APP_USER" == "$DB_ADMIN_USER" ]]; then
  echo "application role must not be the admin role ($DB_ADMIN_USER)" >&2
  exit 2
fi
if ! remote_dir_ok "$REMOTE_DIR"; then
  echo "remote dir must be a relative path without .. (got '$REMOTE_DIR')" >&2
  exit 2
fi
if [[ "$DOCROOT" != /* || "$DOCROOT" == *..* ]]; then
  echo "docroot must be an absolute path without .. (got '$DOCROOT')" >&2
  exit 2
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "port must be an unprivileged TCP port, got: $PORT" >&2
  exit 2
fi

remote_args=(
  --remote-dir "$REMOTE_DIR"
  --port "$PORT"
  --db-name "$DB_NAME"
  --db-app-user "$DB_APP_USER"
  --db-admin-user "$DB_ADMIN_USER"
)
(( DEMO_SEED )) && remote_args+=(--demo-seed)
[[ -n "$INGEST_DIR" ]] && remote_args+=(--ingest "$INGEST_DIR")
(( SKIP_DB )) && remote_args+=(--skip-db)
(( SKIP_UNIT )) && remote_args+=(--skip-unit)
(( SKIP_HTACCESS )) && remote_args+=(--skip-htaccess)
(( RESET_APP_PASSWORD )) && remote_args+=(--reset-app-password)
remote_args+=(--docroot "$DOCROOT")
[[ -n "$PUBLIC_HOST" ]] && remote_args+=(--public-host "$PUBLIC_HOST")

if (( SYNC_ONLY )) && [[ -z "$HOST" ]]; then
  echo "--sync-only requires --host" >&2
  exit 2
fi
if (( SYNC_ONLY && ! SYNC )); then
  echo "--sync-only conflicts with --no-sync" >&2
  exit 2
fi

if [[ -n "$HOST" ]]; then
  if (( SYNC )); then
    echo "==> rsync $ROOT -> $HOST:${REMOTE_DIR}/"
    rsync -az --exclude-from "$ROOT/deploy/rsync-exclude" "$ROOT"/ "$HOST:${REMOTE_DIR}/"
    ssh "$HOST" "chmod +x ${REMOTE_DIR}/scripts/deploy-vm.sh"
  fi
  if (( SYNC_ONLY )); then
    echo "==> sync-only; not running remote deploy"
    exit 0
  fi
  echo "==> running deploy on $HOST as $(ssh "$HOST" 'id -un')"
  # Allocate a TTY so the admin role can be prompted. The password is not stored
  # on the server; it is only forwarded for this hop if already set.
  if [[ -n "${BIB_DB_ADMIN_PASSWORD:-}" ]]; then
    ssh "$HOST" "BIB_DB_ADMIN_PASSWORD=$(printf '%q' "$BIB_DB_ADMIN_PASSWORD") ./${REMOTE_DIR}/scripts/deploy-vm.sh $(printf '%q ' "${remote_args[@]}")"
  else
    ssh -t "$HOST" "./${REMOTE_DIR}/scripts/deploy-vm.sh $(printf '%q ' "${remote_args[@]}")"
  fi
  exit $?
fi

# --- on the server ----------------------------------------------------------

ENV_DIR="${HOME}/.config/bib"
ENV_FILE="${ENV_DIR}/env"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/bib.service"
INSTALL_ROOT="${HOME}/${REMOTE_DIR}"

log() { printf '%s\n' "==> $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

random_secret() {
  python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(32)))'
}

quote_dsn_pw() {
  python3 -c 'import sys,urllib.parse; print(urllib.parse.quote_plus(sys.argv[1], safe=""))' "$1"
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi
  if [[ -x "${HOME}/.local/bin/uv" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
    return
  fi
  log "installing uv into ${HOME}/.local"
  need_cmd curl
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
  command -v uv >/dev/null 2>&1 || {
    echo "uv install did not put uv on PATH" >&2
    exit 1
  }
}

# Print an eval-able psql prefix that can run as the admin role.
discover_admin_psql() {
  local pw="$1"
  local user="$DB_ADMIN_USER"
  local pw_env=""
  if [[ -n "$pw" ]]; then
    pw_env="PGPASSWORD=$(printf '%q' "$pw") "
  fi
  local candidates=(
    "${pw_env}psql -U ${user} -d postgres"
    "${pw_env}psql -U ${user} -h /var/run/postgresql -d postgres"
    "${pw_env}psql -U ${user} -h /run/postgresql -d postgres"
    "${pw_env}PGSSLMODE=require psql -U ${user} -h 127.0.0.1 -p 5432 -d postgres"
    "${pw_env}PGSSLMODE=require PGSSLROOTCERT=/etc/pki/tls/certs/ca-bundle.crt psql -U ${user} -h localhost -p 5432 -d postgres"
    "${pw_env}PGSSLMODE=require PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt psql -U ${user} -h localhost -p 5432 -d postgres"
  )
  if [[ -z "$pw" ]]; then
    candidates+=(
      "psql -d postgres"
      "psql -U ${user} -d postgres"
    )
  fi
  local c
  for c in "${candidates[@]}"; do
    if eval "$c -Atqc 'SELECT 1'" >/dev/null 2>&1; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

write_env_file() {
  local dsn="$1" token="$2" public="$3"
  mkdir -p "$ENV_DIR"
  chmod 700 "$ENV_DIR"
  cat > "$ENV_FILE" <<EOF
# Application environment for bib (systemd --user). Mode 600.
# Privileged database-admin credentials do not belong here or in the checkout.

BIB_DATABASE_URL=${dsn}
BIB_HOST=127.0.0.1
BIB_PORT=${PORT}
BIB_DEBUG=false
BIB_SENTRY_ENVIRONMENT=production
# BIB_EXPOSE_DOCS=false
BIB_FORWARDED_ALLOW_IPS=127.0.0.1
BIB_ALLOWED_HOSTS=${public},localhost,127.0.0.1
BIB_ADMIN_TOKEN=${token}
BIB_ADMIN_PATH=/_ops
EOF
  chmod 600 "$ENV_FILE"
}

ensure_database() {
  local public="$1"
  if [[ -f "$ENV_FILE" && "$RESET_APP_PASSWORD" -eq 0 ]]; then
    log "reusing existing $ENV_FILE"
    return
  fi

  if ! command -v psql >/dev/null 2>&1; then
    echo "PostgreSQL client (psql) is not on PATH. bib requires PostgreSQL." >&2
    exit 1
  fi

  local admin_pw="${BIB_DB_ADMIN_PASSWORD:-}"
  local admin=""
  if admin="$(discover_admin_psql "$admin_pw")"; then
    :
  elif [[ -z "$admin_pw" && -t 0 ]]; then
    read -r -s -p "Password for PostgreSQL role ${DB_ADMIN_USER} (empty for peer/ident): " admin_pw
    echo
    admin="$(discover_admin_psql "$admin_pw")" || true
  fi
  if [[ -z "$admin" ]]; then
    echo "could not connect as ${DB_ADMIN_USER} via socket, peer/ident, or TLS TCP." >&2
    echo "set BIB_DB_ADMIN_PASSWORD or --db-admin-user, and confirm PostgreSQL is running locally." >&2
    exit 1
  fi
  log "connected as ${DB_ADMIN_USER}"

  local app_pw
  app_pw="$(random_secret)"

  # Create (or rotate) the application role. A non-superuser CREATEDB role
  # cannot CREATE DATABASE ... OWNER other_role unless it can SET ROLE to
  # that owner, so grant membership for the create and then revoke it.
  # Identifiers are validated above; app_pw is [A-Za-z0-9] only.
  eval "$admin -v ON_ERROR_STOP=1" <<EOF
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_APP_USER}') THEN
    EXECUTE format('CREATE ROLE ${DB_APP_USER} LOGIN PASSWORD %L', '${app_pw}');
  ELSE
    EXECUTE format('ALTER ROLE ${DB_APP_USER} LOGIN PASSWORD %L', '${app_pw}');
  END IF;
END
\$\$;
GRANT ${DB_APP_USER} TO CURRENT_USER;
SELECT format('CREATE DATABASE ${DB_NAME} OWNER ${DB_APP_USER}')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}');
\\gexec
EOF

  # Schema privileges on the new DB (public.CREATE was revoked for PUBLIC in PG 15+).
  eval "$admin -v ON_ERROR_STOP=1 -d ${DB_NAME}" <<EOF
GRANT ALL ON SCHEMA public TO ${DB_APP_USER};
ALTER SCHEMA public OWNER TO ${DB_APP_USER};
EOF

  eval "$admin -v ON_ERROR_STOP=1" <<EOF
REVOKE ${DB_APP_USER} FROM CURRENT_USER;
EOF
  # REVOKE is hygiene; the database already exists if we got here.

  local dsn_pw host_q dsn
  dsn_pw="$(quote_dsn_pw "$app_pw")"
  # Prefer the Unix socket. Fall back to TCP with sslmode=require.
  if [[ -S /var/run/postgresql/.s.PGSQL.5432 ]]; then
    host_q="/var/run/postgresql"
    dsn="postgresql+psycopg://${DB_APP_USER}:${dsn_pw}@/${DB_NAME}?host=${host_q}"
  elif [[ -S /run/postgresql/.s.PGSQL.5432 ]]; then
    host_q="/run/postgresql"
    dsn="postgresql+psycopg://${DB_APP_USER}:${dsn_pw}@/${DB_NAME}?host=${host_q}"
  else
    dsn="postgresql+psycopg://${DB_APP_USER}:${dsn_pw}@127.0.0.1:5432/${DB_NAME}?sslmode=require"
  fi

  local token=""
  if [[ -f "$ENV_FILE" ]]; then
    token="$(awk -F= '/^BIB_ADMIN_TOKEN=/{print substr($0,16); exit}' "$ENV_FILE" || true)"
  fi
  if [[ -z "$token" ]]; then
    token="$(random_secret)"
    log "generated BIB_ADMIN_TOKEN (operator console at /_ops)"
  fi

  write_env_file "$dsn" "$token" "$public"
  log "wrote $ENV_FILE (application role ${DB_APP_USER} only)"
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

install_unit() {
  mkdir -p "$UNIT_DIR" "${HOME}/.local/state/bib"
  local tmp
  tmp="$(mktemp)"
  sed "s|%h/bib|%h/${REMOTE_DIR}|g; s/127.0.0.1:8001/127.0.0.1:${PORT}/g" \
    "$INSTALL_ROOT/deploy/bib.user.service" > "$tmp"
  mv "$tmp" "$UNIT_FILE"
  if command -v loginctl >/dev/null 2>&1; then
    loginctl enable-linger "$USER" >/dev/null 2>&1 || \
      echo "warning: could not enable linger; check: loginctl user-status \$USER | grep Linger" >&2
  fi
  systemctl --user daemon-reload
  systemctl --user enable bib.service
  systemctl --user restart bib.service
  sleep 1
  systemctl --user --no-pager --full status bib.service || true
}

install_htaccess() {
  local src dest
  src="$INSTALL_ROOT/deploy/htaccess.example"
  dest="${DOCROOT}/.htaccess"
  if [[ ! -d "$DOCROOT" ]]; then
    echo "warning: document root $DOCROOT is missing; skip .htaccess (use --docroot or --skip-htaccess)" >&2
    return
  fi
  if [[ ! -w "$DOCROOT" ]]; then
    echo "warning: cannot write $DOCROOT; skip .htaccess" >&2
    return
  fi
  if [[ -e "$dest" ]] && ! grep -q '^# bib:' "$dest"; then
    echo "warning: $dest exists and is not a bib proxy file; leaving it alone" >&2
    echo "         install $src manually or pass --skip-htaccess" >&2
    return
  fi
  # Copy, do not mv: a rename from $HOME keeps user_home_t and Apache 403s.
  sed "s/127.0.0.1:8001/127.0.0.1:${PORT}/g" "$src" > "$dest"
  chmod a+r "$dest"
  if command -v restorecon >/dev/null 2>&1; then
    restorecon "$dest" || true
  fi
  log "wrote $dest (RewriteRule [P] -> 127.0.0.1:${PORT})"
}

post_deploy_smoke() {
  # Loopback checks against gunicorn (do not need Apache): liveness,
  # readiness (DB reachable + migrated), one real science call, and the
  # security headers the app is supposed to set.
  local base="http://127.0.0.1:${PORT}" body pid
  log "post-deploy smoke on $base"
  for _ in $(seq 1 20); do
    curl -fsS "$base/api/v1/health" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS "$base/api/v1/health" >/dev/null || { echo "smoke: /api/v1/health failed" >&2; return 1; }
  curl -fsS "$base/api/v1/ready" >/dev/null || { echo "smoke: /api/v1/ready failed (database?)" >&2; return 1; }
  pid="$(curl -fsS "$base/api/v1/populations" | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r[0]["id"] if r else "")')"
  if [[ -n "$pid" ]]; then
    body="$(curl -fsS "$base/api/v1/photometry?population_id=${pid}&log_age=8.0&filters=sdss.g")" \
      || { echo "smoke: /api/v1/photometry failed" >&2; return 1; }
    grep -q '"attenuation_label"' <<<"$body" || { echo "smoke: photometry payload lacks attenuation flags" >&2; return 1; }
  else
    echo "smoke: no populations loaded; skipping the photometry call" >&2
  fi
  curl -fsSI "$base/" | grep -qi '^content-security-policy:' \
    || { echo "smoke: Content-Security-Policy header missing" >&2; return 1; }
  log "smoke OK"
}

print_proxy_help() {
  local public="$1"
  cat <<EOF

==> gunicorn listens on 127.0.0.1:${PORT}
    .htaccess in ${DOCROOT} proxies with RewriteRule [P] (copy, not mv).
    If Apache returns 500/403 on that rule, [P] is not allowed: install
    ${INSTALL_ROOT}/deploy/httpd-bib.conf.example in the TLS vhost instead.
    Public host allowlist: ${public}

Check loopback (does not need Apache):

    curl -sS http://127.0.0.1:${PORT}/api/v1/health

Logs:  ~/.local/state/bib/error.log
       (user journald is often unreadable on hosted VMs)
EOF
}

# --- steps ---

if [[ ! -d "$INSTALL_ROOT/src/bib" ]]; then
  echo "expected a bib checkout at $INSTALL_ROOT (rsync with --host, or clone there first)" >&2
  exit 1
fi

cd "$INSTALL_ROOT"

if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="$(hostname -f 2>/dev/null || hostname)"
fi

log "install root $INSTALL_ROOT (public host $PUBLIC_HOST, db admin $DB_ADMIN_USER)"

ensure_uv

if (( ! SKIP_DB )); then
  ensure_database "$PUBLIC_HOST"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE (run without --skip-db on first deploy)" >&2
  exit 1
fi

load_env
log "uv sync --frozen --python 3.13 --extra prod"
uv sync --frozen --python 3.13 --extra prod
# Later `uv run` without --extra prod would drop gunicorn from the venv
# (systemd then fails with 203/EXEC). Keep the prod extra on every invoke.
run_bib() { uv run --frozen --extra prod bib "$@"; }

log "checking gunicorn"
uv run --frozen --extra prod python -c "import gunicorn, uvicorn.workers"

log "bib init-db"
run_bib init-db

if (( DEMO_SEED )); then
  log "bib demo-seed"
  run_bib demo-seed
fi

if [[ -n "$INGEST_DIR" ]]; then
  log "bib ingest --source $INGEST_DIR"
  run_bib ingest --source "$INGEST_DIR" --manifest src/bib/ingest/sed-100.yaml
fi

run_bib info || true

if (( ! SKIP_UNIT )); then
  log "systemd --user bib.service"
  need_cmd systemctl
  install_unit
fi

if (( ! SKIP_HTACCESS )); then
  log "Apache .htaccess in $DOCROOT"
  install_htaccess
fi

if (( ! SKIP_UNIT )); then
  post_deploy_smoke || echo "warning: post-deploy smoke failed; check ~/.local/state/bib/error.log" >&2
fi

print_proxy_help "$PUBLIC_HOST"
