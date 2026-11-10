"""Application settings and branding configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import yaml
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root when running from a checkout; harmless otherwise.
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_COLORS: dict[str, str] = {
    "bg": "#0b1020",
    "surface": "#141b30",
    "surface-2": "#1d2742",
    "border": "#2a3557",
    "text": "#e8ecf8",
    "muted": "#9aa7c7",
    "primary": "#5aa9ff",
    "primary-contrast": "#06121f",
    "accent": "#ffb454",
    "accent-2": "#7ee0a3",
    "warn": "#ff7b72",
    "plot-bg": "#0e1428",
}


class Branding(BaseModel):
    """Visual identity of a deployment, loaded from ``branding.yaml``."""

    site_name: str = "bib"
    full_name: str = "BPASS-in-Browser"
    tagline: str = "Explore binary stellar populations, interactively."
    logo: str | None = None
    source_url: str | None = None
    colors: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_COLORS))
    footer_note: str = ""

    def css_variables(self) -> str:
        """Render the palette as CSS custom properties for the base template."""
        merged = {**DEFAULT_COLORS, **self.colors}
        lines = [f"--brand-{key}: {value};" for key, value in merged.items()]
        return "\n    ".join(lines)


# User-level file written by scripts/deploy-vm.sh (systemd EnvironmentFile).
_USER_ENV = Path.home() / ".config" / "bib" / "env"


def parse_goatcounter_url(raw: str | None) -> str | None:
    """Return a safe ``https://…/count`` endpoint, or None if unset/invalid."""
    text = (raw or "").strip()
    if not text or any(ch in text for ch in "<>\"'` \t\n\r"):
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.fragment:
        return None
    path = parsed.path if parsed.path not in ("", "/") else "/count"
    if "//" in path:
        return None
    return urlunparse(
        ("https", parsed.netloc.lower(), path.rstrip("/") or "/count", "", "", "")
    )


def _settings_env_files() -> tuple[Path, str]:
    """Deploy env first, then cwd ``.env`` (later file wins). Missing files are skipped."""
    return (_USER_ENV, ".env")


class Settings(BaseSettings):
    """Runtime settings. Every field can be set via ``BIB_*`` env vars."""

    model_config = SettingsConfigDict(
        env_prefix="BIB_",
        env_file=(_USER_ENV, ".env"),
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://bib:bib@localhost:5432/bib",
        validation_alias=AliasChoices("BIB_DATABASE_URL", "DATABASE_URL"),
    )
    host: str = "0.0.0.0"
    port: int = 8000
    branding_file: Path | None = None
    debug: bool = False

    # Directory holding bundled filter transmission curves.
    filters_dir: Path = _REPO_ROOT / "data" / "filters"

    admin_path: str = "/_ops"
    admin_token: str = ""
    sentry_dsn: str = Field(
        default="",
        validation_alias=AliasChoices("BIB_SENTRY_DSN", "SENTRY_DSN"),
    )
    sentry_environment: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BIB_SENTRY_ENVIRONMENT", "SENTRY_ENVIRONMENT"),
    )
    allowed_hosts: str = ""
    expose_docs: bool | None = None
    log_json: bool | None = None
    rate_limit_per_minute: int = 40
    custom_filter_rate_limit_per_minute: int = 40
    stats_flush_seconds: int = 60
    # Cookieless GoatCounter pixel, e.g. https://SITE.goatcounter.com/count
    goatcounter_url: str = ""
    # Comma-separated IPs uvicorn trusts for X-Forwarded-* (default: local proxy).
    forwarded_allow_ips: str = "127.0.0.1"

    @property
    def normalized_admin_path(self) -> str:
        raw = (self.admin_path or "/_ops").strip() or "/_ops"
        if not raw.startswith("/"):
            raw = f"/{raw}"
        raw = raw.rstrip("/") or "/_ops"
        if raw in {
            "/",
            "/api",
            "/static",
            "/ssp",
            "/sed",
            "/hr",
            "/star",
            "/about",
            "/data",
            "/tutorial",
            "/privacy",
        }:
            return "/_ops"
        return raw

    @property
    def goatcounter_endpoint(self) -> str | None:
        return parse_goatcounter_url(self.goatcounter_url)

    @property
    def goatcounter_origin(self) -> str | None:
        endpoint = self.goatcounter_endpoint
        if not endpoint:
            return None
        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def should_expose_docs(self) -> bool:
        if self.expose_docs is None:
            return True
        return self.expose_docs

    @property
    def should_log_json(self) -> bool:
        if self.log_json is None:
            return not self.debug
        return self.log_json

    @property
    def sentry_environment_name(self) -> str:
        if self.sentry_environment:
            return self.sentry_environment.strip()
        return "development" if self.debug else "production"

    def load_branding(self) -> Branding:
        candidates = [self.branding_file] if self.branding_file else []
        candidates += [Path.cwd() / "branding.yaml", _REPO_ROOT / "branding.yaml"]
        for candidate in candidates:
            if candidate and candidate.is_file():
                raw: dict[str, Any] = yaml.safe_load(candidate.read_text()) or {}
                return Branding.model_validate(raw)
        return Branding()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(_env_file=_settings_env_files())


@lru_cache(maxsize=1)
def get_branding() -> Branding:
    return get_settings().load_branding()
