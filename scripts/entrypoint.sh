#!/bin/sh
# bib container entrypoint.
# Waits for the database, initialises the schema, optionally seeds demo data,
# then execs the requested command (default: serve).
set -e

echo "[bib] waiting for database..."
python - <<'PY'
import os, sys, time
import psycopg
url = os.environ.get("DATABASE_URL", "postgresql+psycopg://bib:bib@localhost:5432/bib")
dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
for attempt in range(120):
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
        print("[bib] database is up")
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("[bib] ERROR: database never became ready", file=sys.stderr)
sys.exit(1)
PY

echo "[bib] initialising schema"
bib init-db

if [ "${BIB_DEMO_SEED:-0}" = "1" ]; then
  echo "[bib] seeding synthetic demo data (if not already present)"
  bib demo-seed || echo "[bib] demo seed skipped/failed (continuing)"
fi

if [ "$1" = "serve" ]; then
  echo "[bib] starting server on 0.0.0.0:8000"
  exec bib serve
fi

exec "$@"
