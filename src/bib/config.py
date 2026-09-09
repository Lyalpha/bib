"""Application settings and branding configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

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
    colors: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_COLORS))
    footer_note: str = ""

    def css_variables(self) -> str:
        """Render the palette as CSS custom properties for the base template."""
        merged = {**DEFAULT_COLORS, **self.colors}
        lines = [f"--brand-{key}: {value};" for key, value in merged.items()]
        return "\n    ".join(lines)


class Settings(BaseSettings):
    """Runtime settings. Every field can be set via ``BIB_*`` env vars."""

    model_config = SettingsConfigDict(env_prefix="BIB_", env_file=".env", extra="ignore")

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
    return Settings()


@lru_cache(maxsize=1)
def get_branding() -> Branding:
    return get_settings().load_branding()
