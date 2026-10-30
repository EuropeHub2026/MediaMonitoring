"""Shared settings for every pipeline script.

Reads `config.yaml` and secrets from the environment. A local `.env` is loaded first but
never overrides variables that are already set, so Codespaces secrets and `.env` are read
the same way.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"
PLACEHOLDER_EMAIL_DOMAIN = "example.org"

log = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when a required setting or secret is missing or invalid."""


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load `config.yaml` (or `path`) and the environment, returning the settings dict."""
    load_dotenv(ROOT / ".env", override=False)
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    for key in ("project", "timezone", "paths", "outlet_groups", "http"):
        if key not in cfg:
            raise ConfigError(f"{config_path}: missing top-level key '{key}'")
    return cfg


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """Return the default config, loaded once per process."""
    return load_config()


def get_secret(name: str, required: bool = True) -> str | None:
    """Return an environment variable, raising ConfigError if required and unset."""
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            raise ConfigError(
                f"Secret {name} is not set. Add it as a Codespaces secret or in .env."
            )
        return None
    return value


def path(cfg: dict[str, Any], key: str) -> Path:
    """Return an absolute path for a `paths:` entry, relative to the repository root."""
    try:
        return ROOT / cfg["paths"][key]
    except KeyError as exc:
        raise ConfigError(f"config.yaml: paths.{key} is not defined") from exc


def tz(cfg: dict[str, Any]) -> ZoneInfo:
    """Return the project time zone (CET, Europe/Belgrade)."""
    return ZoneInfo(cfg["timezone"])


def now(cfg: dict[str, Any]) -> datetime:
    """Return the current time in the project time zone."""
    return datetime.now(tz(cfg))


def iso(dt: datetime, cfg: dict[str, Any]) -> str:
    """Format a datetime as ISO 8601 with the CET/CEST offset; naive values are assumed UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(tz(cfg)).isoformat(timespec="seconds")


def user_agent(cfg: dict[str, Any]) -> str:
    """Return the HTTP User-Agent naming the project and a contact address.

    Refuses to build one while `project.contact_email` is still the placeholder, so no
    collector can run without a real contact.
    """
    project = cfg["project"]
    email = str(project.get("contact_email", "")).strip()
    if "@" not in email or email.endswith("@" + PLACEHOLDER_EMAIL_DOMAIN):
        raise ConfigError(
            "Set project.contact_email in config.yaml to a real address before collecting."
        )
    return f"{project['user_agent_name']} (+{project['repo_url']}; contact: {email})"


def setup_logging(script_name: str, cfg: dict[str, Any] | None = None) -> logging.Logger:
    """Configure logging to stderr and, when a config is given, to data/logs/<script>.log."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if cfg is not None:
        log_dir = path(cfg, "log_dir")
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / f"{script_name}.log", encoding="utf-8"))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    if cfg is not None:
        zone = tz(cfg)
        formatter.converter = lambda secs: datetime.fromtimestamp(secs, zone).timetuple()
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    return logging.getLogger(script_name)
