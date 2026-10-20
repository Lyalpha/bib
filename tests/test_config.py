"""Settings load order: process env, cwd .env, then ~/.config/bib/env."""

from __future__ import annotations

from bib.config import Settings, get_settings


def test_user_config_env_used_when_cwd_has_no_dotenv(tmp_path, monkeypatch):
    home = tmp_path / "home"
    env_path = home / ".config" / "bib" / "env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("BIB_DATABASE_URL=postgresql+psycopg://bib_app:secret@127.0.0.1:5432/bib\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BIB_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        settings = Settings(_env_file=(env_path, ".env"))
        assert "bib_app:secret@" in settings.database_url
    finally:
        get_settings.cache_clear()


def test_cwd_dotenv_overrides_user_config_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    env_path = home / ".config" / "bib" / "env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("BIB_DATABASE_URL=postgresql+psycopg://bib_app:secret@127.0.0.1:5432/bib\n")
    (tmp_path / ".env").write_text(
        "BIB_DATABASE_URL=postgresql+psycopg://local:dev@localhost:5433/bib_test\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BIB_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        settings = Settings(_env_file=(env_path, ".env"))
        assert "local:dev@" in settings.database_url
        assert "bib_app" not in settings.database_url
    finally:
        get_settings.cache_clear()
