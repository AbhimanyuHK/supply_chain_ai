import os

from app.core.config import Settings, get_settings


def test_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./unit_test.db")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("FLEET_MODULE_ENABLED", "true")

    settings = Settings()

    assert settings.database_url == "sqlite+aiosqlite:///./unit_test.db"
    assert settings.groq_model == "llama-3.3-70b-versatile"
    assert settings.fleet_module_enabled is True


def test_settings_defaults_apply(monkeypatch):
    for key in ("FLEET_MODULE_ENABLED", "LOG_LEVEL", "APP_ENV"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.fleet_module_enabled is False
    assert settings.log_level == "INFO"
    assert settings.app_env == "development"


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_current_test_environment_uses_isolated_sqlite_db():
    settings = get_settings()
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert "test_supply_chain.db" in settings.database_url
    assert os.environ["APP_ENV"] == "test"
