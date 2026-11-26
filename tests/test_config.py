
import pytest
from pydantic import ValidationError

from medusa.core.config import PROJECT_ROOT, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith("MEDUSA_"):
            monkeypatch.delenv(key)


def test_defaults():
    s = Settings(_env_file=None)
    assert s.environment == "development" and s.api_port == 8000 and s.log_format == "text"
    assert s.db_path == PROJECT_ROOT / "data" / "medusa.db"
    assert s.log_file is None and s.docs_enabled


def test_environment_variables_override(monkeypatch):
    monkeypatch.setenv("MEDUSA_API_PORT", "9001")
    monkeypatch.setenv("MEDUSA_LOG_LEVEL", "debug")
    monkeypatch.setenv("MEDUSA_ENVIRONMENT", "production")
    s = Settings(_env_file=None)
    assert s.api_port == 9001 and s.log_level == "DEBUG" and not s.docs_enabled


def test_env_file_is_loaded(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MEDUSA_DB_PATH=custom/x.db\nMEDUSA_LOG_FORMAT=json\nMEDUSA_API_URL=http://ignored\n")
    s = Settings(_env_file=env)
    assert s.db_path == (PROJECT_ROOT / "custom" / "x.db").resolve() and s.log_format == "json"


def test_absolute_paths_kept(tmp_path):
    assert Settings(_env_file=None, db_path=tmp_path / "a.db").db_path == tmp_path / "a.db"


def test_empty_log_file_means_console_only(monkeypatch):
    monkeypatch.setenv("MEDUSA_LOG_FILE", "")
    assert Settings(_env_file=None).log_file is None


@pytest.mark.parametrize("key,value", [
    ("MEDUSA_API_PORT", "70000"),
    ("MEDUSA_ENVIRONMENT", "staging"),
    ("MEDUSA_LOG_FORMAT", "xml"),
    ("MEDUSA_LOG_LEVEL", "verbose"),
])
def test_invalid_values_rejected(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_example_is_valid():
    """Guards against .env.example drifting away from the Settings model."""
    example = PROJECT_ROOT / ".env.example"
    s = Settings(_env_file=example)
    assert s.environment == "development" and s.db_path.name == "medusa.db"
    keys = {line.split("=", 1)[0] for line in example.read_text().splitlines() if "=" in line and not line.startswith("#")}
    backend_keys = {f"MEDUSA_{name.upper()}" for name in Settings.model_fields}
    assert keys - {"MEDUSA_API_URL"} <= backend_keys
