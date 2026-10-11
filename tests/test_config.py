"""Settings from the environment and from ``.env`` in the working directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from tna_discovery_mcp.config import ConfigError, load_config

VARIABLES = (
    "TNA_DISCOVERY_TIMEOUT",
    "TNA_DISCOVERY_MIN_INTERVAL",
    "TNA_DISCOVERY_DAILY_BUDGET",
    "TNA_DISCOVERY_CONTACT",
    "TNA_DISCOVERY_STATE_DIR",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_nothing_is_required_and_the_defaults_are_tnas_guideline():
    cfg = load_config()
    assert cfg.timeout == 30.0 and cfg.contact == ""
    assert cfg.min_interval == 1.0 and cfg.daily_budget == 3_000
    assert cfg.state_dir == Path.home() / ".local" / "state" / "tna-discovery-mcp"


def test_every_setting_is_read(monkeypatch, tmp_path):
    monkeypatch.setenv("TNA_DISCOVERY_TIMEOUT", "15")
    monkeypatch.setenv("TNA_DISCOVERY_MIN_INTERVAL", "2.5")
    monkeypatch.setenv("TNA_DISCOVERY_DAILY_BUDGET", "500")
    monkeypatch.setenv("TNA_DISCOVERY_CONTACT", "me@example.org")
    monkeypatch.setenv("TNA_DISCOVERY_STATE_DIR", str(tmp_path / "s"))
    cfg = load_config()
    assert (cfg.timeout, cfg.min_interval, cfg.daily_budget) == (15.0, 2.5, 500)
    assert cfg.contact == "me@example.org" and cfg.state_dir == tmp_path / "s"


@pytest.mark.parametrize("raw", ["thirty", "0", "-5", "nan", "inf"])
def test_an_unusable_timeout_names_the_variable(monkeypatch, raw):
    monkeypatch.setenv("TNA_DISCOVERY_TIMEOUT", raw)
    with pytest.raises(ConfigError, match="TNA_DISCOVERY_TIMEOUT"):
        load_config()


@pytest.mark.parametrize("raw", ["0.5", "0.99"])
def test_the_interval_cannot_go_below_one_second(monkeypatch, raw):
    monkeypatch.setenv("TNA_DISCOVERY_MIN_INTERVAL", raw)
    with pytest.raises(ConfigError, match="at least 1"):
        load_config()


@pytest.mark.parametrize("raw", ["3001", "10000", "0", "-1", "lots", "1.5"])
def test_the_budget_cannot_exceed_the_guideline_or_be_nonsense(monkeypatch, raw):
    monkeypatch.setenv("TNA_DISCOVERY_DAILY_BUDGET", raw)
    with pytest.raises(ConfigError, match="TNA_DISCOVERY_DAILY_BUDGET"):
        load_config()


@pytest.mark.parametrize("raw", ["me@example.org\r\nX-Evil: 1", "me (home)"])
def test_a_contact_that_could_break_the_header_is_refused(monkeypatch, raw):
    monkeypatch.setenv("TNA_DISCOVERY_CONTACT", raw)
    with pytest.raises(ConfigError, match="TNA_DISCOVERY_CONTACT"):
        load_config()


def test_a_relative_state_directory_is_refused(monkeypatch):
    monkeypatch.setenv("TNA_DISCOVERY_STATE_DIR", "state")
    with pytest.raises(ConfigError, match="TNA_DISCOVERY_STATE_DIR"):
        load_config()


def test_dot_env_in_the_working_directory_is_read(tmp_path):
    (tmp_path / ".env").write_text("TNA_DISCOVERY_TIMEOUT=7\n")
    assert load_config().timeout == 7.0


def test_the_environment_wins_over_dot_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("TNA_DISCOVERY_TIMEOUT=7\n")
    monkeypatch.setenv("TNA_DISCOVERY_TIMEOUT", "9")
    assert load_config().timeout == 9.0
