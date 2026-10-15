"""Bare-metal deploy artifacts: user systemd unit, Apache snippets, script."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-vm.sh"
UNIT = ROOT / "deploy" / "bib.user.service"
HTTPD = ROOT / "deploy" / "httpd-bib.conf.example"
HTACCESS = ROOT / "deploy" / "htaccess.example"
RSYNC_EXCLUDE = ROOT / "deploy" / "rsync-exclude"

SITE_SPECIFIC = (
    "warwick",
    "bib-svc",
    "svc_user",
    "db_user",
    "cyan-quail",
    "helpdesk",
    "ssh2fa",
    "nrpe",
    "idg",
)


def test_deploy_script_is_valid_bash():
    assert SCRIPT.is_file()
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_deploy_artifacts_are_site_agnostic():
    blob = "\n".join(
        path.read_text().lower()
        for path in (SCRIPT, UNIT, HTTPD, HTACCESS, RSYNC_EXCLUDE)
    )
    for needle in SITE_SPECIFIC:
        assert needle not in blob, needle


def test_user_unit_runs_gunicorn_on_loopback():
    text = UNIT.read_text()
    assert "WantedBy=default.target" in text
    assert "User=" not in text
    assert "multi-user.target" not in text
    assert "127.0.0.1:8001" in text
    assert "python -m gunicorn" in text
    assert "bib.app:create_app()" in text
    assert " --factory" not in text
    assert "EnvironmentFile=%h/.config/bib/env" in text
    assert "WorkingDirectory=%h/bib" in text


def test_htaccess_is_a_proxy_not_a_client_redirect():
    text = HTACCESS.read_text()
    assert "RewriteEngine On" in text
    assert r"^index\.html$" in text
    assert "RewriteRule ^$" in text
    assert not any(line.startswith("DirectoryIndex") for line in text.splitlines())
    assert "RewriteRule" in text
    assert "[P,L]" in text
    assert "http://127.0.0.1:8001/" in text
    assert "R=302" not in text
    assert "0.0.0.0" not in text


def test_httpd_snippet_proxies_loopback_only():
    text = HTTPD.read_text()
    assert "ProxyPass / http://127.0.0.1:8001/" in text
    assert "X-Forwarded-Proto" in text
    assert "LimitRequestBody 2097152" in text
    assert "0.0.0.0" not in text


def test_deploy_script_keeps_admin_role_out_of_app_env():
    text = SCRIPT.read_text()
    assert "--db-admin-user" in text
    assert "load_deploy_dotenv" in text
    assert "BIB_DB_ADMIN_USER" in text
    assert "GRANT ${DB_APP_USER} TO CURRENT_USER" in text
    assert "REVOKE ${DB_APP_USER} FROM CURRENT_USER" in text
    assert "Privileged database-admin credentials do not belong here" in text
    assert "uv run --frozen --extra prod" in text
    assert "systemctl --user" in text
    assert "loginctl enable-linger" in text
    assert "install_htaccess" in text
    assert "do not mv" in text.lower()
    assert "--host your.server.example" in text
    assert "--sync-only" in text
    assert "not running remote deploy" in text


def test_rsync_exclude_keeps_secrets_and_raw_data_off_the_server():
    text = RSYNC_EXCLUDE.read_text()
    for name in (".venv", ".env", "data/raw/", "*.tar.gz"):
        assert name in text
