from pathlib import Path

import pytest

from sidereal import paths
from sidereal.config import ConfigError, Settings, env_overrides, load_settings


def test_defaults_without_a_config_file(isolated_env: Path):
    s = load_settings()
    assert s.web.host == "127.0.0.1"
    assert s.web.port == 8470
    assert s.web.allowed_hosts == ["127.0.0.1", "localhost"]
    assert s.auth.mode == "off"
    assert s.schedule.tz == "Europe/London"
    assert s.budget.max_assess_per_run == 40
    assert s.models.never_unload == ["qwen3.6:35b-a3b-coding"]
    assert s.state_dir == isolated_env / ".local" / "share" / "sidereal"
    assert s.db_path == s.state_dir / "sidereal.db"


def test_toml_file_is_read(config_file: Path):
    config_file.write_text('[web]\nport = 9000\n[budget]\nmax_assess_per_run = 5\n')
    s = load_settings()
    assert s.web.port == 9000
    assert s.budget.max_assess_per_run == 5


def test_env_overrides_file_and_parses_json(config_file: Path, monkeypatch):
    config_file.write_text("[web]\nport = 9000\n")
    monkeypatch.setenv("SIDEREAL_WEB__PORT", "9100")
    monkeypatch.setenv("SIDEREAL_WEB__ALLOWED_HOSTS", '["vm.lan"]')
    monkeypatch.setenv("SIDEREAL_OLLAMA__URL", "http://ollama.test:11434")
    s = load_settings()
    assert s.web.port == 9100
    assert s.web.allowed_hosts == ["vm.lan"]
    assert s.ollama.url == "http://ollama.test:11434"


def test_sidereal_config_points_at_another_file(tmp_path: Path, monkeypatch):
    other = tmp_path / "other.toml"
    other.write_text('[paths]\nstate_dir = "%s"\n' % (tmp_path / "st"))
    monkeypatch.setenv("SIDEREAL_CONFIG", str(other))
    assert paths.config_file() == other
    assert load_settings().state_dir == tmp_path / "st"


def test_env_state_dir_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SIDEREAL_PATHS__STATE_DIR", str(tmp_path / "state"))
    assert load_settings().db_path == tmp_path / "state" / "sidereal.db"


def test_variables_without_double_underscore_are_ignored():
    assert env_overrides({"SIDEREAL_SMTP_PASSWORD": "x", "SIDEREAL_CONFIG": "/x"}) == {}


@pytest.mark.parametrize(
    ("text", "env"),
    [
        ("[web]\nprot = 1\n", {}),  # unknown key
        ("[nonsense]\na = 1\n", {}),  # unknown section
        ("[schedule]\ntz = 'Mars/Olympus'\n", {}),
        ("[web\n", {}),  # TOML syntax error
        ("", {"SIDEREAL_BOGUS__KEY": "1"}),
        ("", {"SIDEREAL_WEB__PORT": "not-a-port"}),
    ],
)
def test_invalid_settings_raise_config_error(config_file: Path, monkeypatch, text, env):
    config_file.write_text(text)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError):
        load_settings()


def test_example_config_is_valid(monkeypatch):
    example = paths.project_root() / "config" / "sidereal.example.toml"
    assert example.is_file()
    monkeypatch.setenv("SIDEREAL_CONFIG", str(example))
    assert isinstance(load_settings(), Settings)
