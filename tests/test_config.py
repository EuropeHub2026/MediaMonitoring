"""Tests for config.py: loading, secrets, time zone and User-Agent."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

import config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg() -> dict:
    return config.load_config(FIXTURES / "config_min.yaml")


def test_load_config_reads_fixture(cfg: dict) -> None:
    assert cfg["timezone"] == "Europe/Belgrade"
    assert "aggregator" in cfg["outlet_groups"]


def test_load_config_rejects_missing_keys(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("project: {}\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load_config(bad)


def test_repo_config_loads() -> None:
    cfg = config.load_config()
    assert cfg["timezone"] == "Europe/Belgrade"
    assert cfg["http"]["min_seconds_between_requests_per_domain"] >= 2
    assert 403 not in cfg["http"]["retry_statuses"]
    assert 429 not in cfg["http"]["retry_statuses"]


def test_get_secret_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SECRET_X", "  value  ")
    assert config.get_secret("TEST_SECRET_X") == "value"


def test_get_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_SECRET_MISSING", raising=False)
    assert config.get_secret("TEST_SECRET_MISSING", required=False) is None
    with pytest.raises(config.ConfigError):
        config.get_secret("TEST_SECRET_MISSING")


def test_iso_uses_cet_offset(cfg: dict) -> None:
    winter = datetime(2026, 11, 2, 5, 0, tzinfo=timezone.utc)
    assert config.iso(winter, cfg) == "2026-11-02T06:00:00+01:00"
    naive_utc = datetime(2026, 11, 2, 5, 0)
    assert config.iso(naive_utc, cfg) == "2026-11-02T06:00:00+01:00"


def test_user_agent_refuses_placeholder(cfg: dict) -> None:
    with pytest.raises(config.ConfigError):
        config.user_agent(cfg)


def test_user_agent_names_project_and_contact(cfg: dict) -> None:
    cfg["project"]["contact_email"] = "team@monitor.test"
    ua = config.user_agent(cfg)
    assert ua.startswith("TestMonitor/0.0")
    assert "team@monitor.test" in ua


def test_path_is_under_repo_root(cfg: dict) -> None:
    assert config.path(cfg, "data_dir") == config.ROOT / "data"
    with pytest.raises(config.ConfigError):
        config.path(cfg, "no_such_key")
