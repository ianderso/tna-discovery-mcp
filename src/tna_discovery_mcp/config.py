"""Configuration from environment variables.

=================================  =============================================
``TNA_DISCOVERY_TIMEOUT``          HTTP timeout in seconds for one request.
``TNA_DISCOVERY_MIN_INTERVAL``     Least seconds between two requests. Never
                                   below 1, TNA's guideline.
``TNA_DISCOVERY_DAILY_BUDGET``     Requests a day before tools refuse. At most
                                   3,000, TNA's guideline.
``TNA_DISCOVERY_CONTACT``          An email address or URL appended to the
                                   User-Agent, so TNA can reach whoever runs
                                   this server.
``TNA_DISCOVERY_STATE_DIR``        Directory for the day's call count, the one
                                   file this server writes. It holds a date
                                   and a number, never anything the API
                                   returned.
=================================  =============================================

None is required: Discovery's API needs no key and no account. A ``.env``
file in the working directory supplies any of these that the environment does
not. There is no cache directory, because TNA's terms ask developers not to
cache or store what the API returns, and no download folder, because no tool
downloads anything.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

#: Least seconds between requests, unless configured otherwise. TNA's terms
#: give "no more frequently than one request per second" as a guideline.
DEFAULT_MIN_INTERVAL = 1.0

#: The floor on TNA_DISCOVERY_MIN_INTERVAL: TNA's guideline, which a setting
#: may slow but never quicken.
MIN_INTERVAL_FLOOR = 1.0

#: Requests a day, unless configured otherwise: TNA's guideline of "no more
#: than 3,000 API calls per day", which is also the ceiling.
DEFAULT_DAILY_BUDGET = 3_000
DAILY_BUDGET_CEILING = 3_000


class ConfigError(RuntimeError):
    """Raised when a setting is present but unusable."""


@dataclass
class Config:
    """Resolved server configuration.

    Attributes
    ----------
    timeout : float
        HTTP timeout in seconds for one request.
    min_interval : float
        Least seconds between the start of one request and the next.
    daily_budget : int
        Requests a day (UTC) before every tool refuses with ``budget_spent``.
    contact : str
        Appended to the User-Agent when set. Empty by default.
    state_dir : Path
        Where the day's call count is kept.
    """

    timeout: float = 30.0
    min_interval: float = DEFAULT_MIN_INTERVAL
    daily_budget: int = DEFAULT_DAILY_BUDGET
    contact: str = ""
    state_dir: Path = field(
        default_factory=lambda: Path.home() / ".local" / "state" / "tna-discovery-mcp"
    )


def load_config() -> Config:
    """Load configuration from the environment.

    A ``.env`` file in the working directory is read if present; real
    environment variables win. Only the working directory is consulted.
    ``load_dotenv()`` with no path searches upward from the *calling
    module's* location instead, which for an installed package is
    ``site-packages``.

    Raises
    ------
    ConfigError
        If a number is unusable, a limit would be loosened past TNA's
        guideline, or a contact string could break the header. The server
        loads its configuration on the first tool call, so this surfaces there
        as a ``not_configured`` result rather than as a crash.
    """
    load_dotenv(Path.cwd() / ".env")

    cfg = Config()
    if raw := os.environ.get("TNA_DISCOVERY_TIMEOUT"):
        cfg.timeout = _positive("TNA_DISCOVERY_TIMEOUT", raw)
    if raw := os.environ.get("TNA_DISCOVERY_MIN_INTERVAL"):
        value = _positive("TNA_DISCOVERY_MIN_INTERVAL", raw)
        if value < MIN_INTERVAL_FLOOR:
            raise ConfigError(
                f"TNA_DISCOVERY_MIN_INTERVAL must be at least {MIN_INTERVAL_FLOOR:g}, TNA's "
                f"guideline of one request a second; got {raw!r}."
            )
        cfg.min_interval = value
    if raw := os.environ.get("TNA_DISCOVERY_DAILY_BUDGET"):
        cfg.daily_budget = _budget(raw)
    if raw := os.environ.get("TNA_DISCOVERY_CONTACT"):
        cfg.contact = _contact(raw)
    if raw := os.environ.get("TNA_DISCOVERY_STATE_DIR"):
        cfg.state_dir = _state_dir(raw)
    return cfg


def _positive(name: str, raw: str) -> float:
    """Parse one numeric setting, naming the variable if it is unusable."""
    try:
        value = float(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} must be a number; got {raw!r}.") from None
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{name} must be greater than zero; got {raw!r}.")
    return value


def _budget(raw: str) -> int:
    """The daily budget: a whole number from 1 to TNA's guideline."""
    text = raw.strip()
    if not text.isdigit() or not 1 <= int(text) <= DAILY_BUDGET_CEILING:
        raise ConfigError(
            f"TNA_DISCOVERY_DAILY_BUDGET must be a whole number from 1 to "
            f"{DAILY_BUDGET_CEILING:,}, TNA's guideline for a day; got {raw!r}."
        )
    return int(text)


def _contact(raw: str) -> str:
    """Keep a contact string safe to place inside a User-Agent header.

    A newline would let the value inject a second header, and parentheses
    would close the comment it sits in.
    """
    text = raw.strip()
    if any(ch in text for ch in "\r\n()") or not text.isprintable():
        raise ConfigError(
            "TNA_DISCOVERY_CONTACT must be one line with no parentheses, such as an "
            f"email address or a URL; got {raw!r}."
        )
    return text


def _state_dir(raw: str) -> Path:
    """Where the call count lives: an absolute path."""
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"TNA_DISCOVERY_STATE_DIR must be an absolute path; got {raw!r}.")
    return path
