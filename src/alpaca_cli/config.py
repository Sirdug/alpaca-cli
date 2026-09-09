"""Profile and credential storage.

Credentials are resolved in this order:

1. Environment variables ``ALPACA_API_KEY`` / ``ALPACA_SECRET_KEY``
   (``ALPACA_LIVE_TRADE=true`` switches them to the live endpoint).
2. The named profile in ``~/.config/alpaca-cli/config.json``.

The config file looks like::

    {
        "default_profile": "default",
        "profiles": {
            "default": {"api_key": "...", "secret_key": "...", "mode": "paper"}
        }
    }
"""

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path(os.environ.get("ALPACA_CONFIG_DIR", "~/.config/alpaca-cli")).expanduser()
CONFIG_PATH = CONFIG_DIR / "config.json"

PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE = "https://api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


class ConfigError(Exception):
    pass


@dataclass
class Credentials:
    api_key: str
    secret_key: str
    paper: bool
    source: str  # "env" or "profile:<name>"

    @property
    def trading_base(self) -> str:
        return PAPER_BASE if self.paper else LIVE_BASE


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"default_profile": "default", "profiles": {}}
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"Could not read {CONFIG_PATH}: {e}")


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    # Keys live in this file; keep it readable by the owner only.
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)


def get_finnhub_key() -> Optional[str]:
    """Finnhub API key: env FINNHUB_API_KEY, else config file."""
    key = os.environ.get("FINNHUB_API_KEY")
    if key:
        return key.strip()
    return (load_config().get("finnhub_api_key") or "").strip() or None


def resolve_credentials(profile: Optional[str] = None) -> Credentials:
    env_key = os.environ.get("ALPACA_API_KEY")
    env_secret = os.environ.get("ALPACA_SECRET_KEY")
    env_secret = os.environ.get("ALPACA_SECRET_KEY")
    if env_key and env_secret and profile is None:
        live = os.environ.get("ALPACA_LIVE_TRADE", "").lower() in ("1", "true", "yes")
        return Credentials(env_key, env_secret, paper=not live, source="env")

    config = load_config()
    name = profile or config.get("default_profile", "default")
    profiles = config.get("profiles", {})
    if name not in profiles:
        if profile is not None:
            raise ConfigError(
                f"Profile '{name}' not found. Run 'alpaca setup --profile {name}' to create it."
            )
        raise ConfigError(
            "No credentials found. Run 'alpaca setup' to save your API keys, or set "
            "ALPACA_API_KEY and ALPACA_SECRET_KEY."
        )
    p = profiles[name]
    return Credentials(
        api_key=p["api_key"],
        secret_key=p["secret_key"],
        paper=p.get("mode", "paper") != "live",
        source=f"profile:{name}",
    )
