"""Settings, loaded from environment variables and an optional ``.env`` file.

Every limit is validated at startup. A bot that runs unattended must refuse to
start on a typo'd risk setting rather than trade on a silently-defaulted one,
so :func:`load_settings` collects *all* problems and raises one
:class:`ConfigError` listing them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import time
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PACKAGE_DIR / ".env"

T = TypeVar("T")


class ConfigError(ValueError):
    """Raised when the environment does not describe a valid configuration."""


class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class DailyLossBasis(str, Enum):
    # Limit is a % of the initial account size (FTMO, most crypto props).
    INITIAL = "initial"
    # Limit is a % of the day's starting reference (max of balance/equity).
    DAY_START = "day_start"


class DrawdownMode(str, Enum):
    # Floor fixed at initial balance minus the allowance.
    STATIC = "static"
    # Floor trails the highest equity seen, including unrealized (Apex-style).
    TRAILING_INTRADAY = "trailing_intraday"
    # Floor trails the highest end-of-day balance (Topstep-style).
    TRAILING_EOD = "trailing_eod"


class NewsSource(str, Enum):
    NONE = "none"
    FILE = "file"
    FOREXFACTORY = "forexfactory"


class Secret:
    """A string that never shows up in logs, reprs or tracebacks."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('***')" if self._value else "Secret('')"

    __str__ = __repr__


@dataclass(frozen=True)
class AccountConfig:
    account_id: str
    initial_balance: float


@dataclass(frozen=True)
class RiskLimits:
    daily_loss_limit_pct: float = 1.5
    daily_loss_basis: DailyLossBasis = DailyLossBasis.INITIAL
    max_drawdown_pct: float = 5.0
    max_drawdown_mode: DrawdownMode = DrawdownMode.TRAILING_INTRADAY
    # Stop trailing once the floor reaches the initial balance (Apex/Topstep).
    drawdown_lock_at_initial: bool = True
    risk_per_trade_pct: float = 0.5
    max_trades_per_day: int = 5
    # Deny new trades if the latest equity snapshot is older than this.
    equity_stale_seconds: int = 120
    # Size no trade to lose more than this share of the distance to the
    # nearest loss floor; the rest absorbs slippage on the stop.
    room_usage_fraction: float = 0.8


@dataclass(frozen=True)
class SessionConfig:
    """When the prop firm's trading day rolls over and daily limits reset."""

    reset_tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("America/New_York"))
    reset_time: time = time(17, 0)


@dataclass(frozen=True)
class NewsConfig:
    source: NewsSource = NewsSource.FOREXFACTORY
    url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    file: Path | None = None
    cache_file: Path = PACKAGE_DIR / "state" / "calendar_cache.json"
    minutes_before: int = 15
    minutes_after: int = 15
    currencies: tuple[str, ...] = ("USD",)
    # Titles containing these are treated as high impact regardless of the
    # feed's own rating.
    keywords: tuple[str, ...] = (
        "CPI", "FOMC", "Federal Funds Rate", "Non-Farm", "NFP", "PCE",
        "GDP", "Powell", "PPI", "Retail Sales", "Unemployment Rate",
    )
    refresh_minutes: int = 360
    # With no fresh calendar data, block trading rather than trade blind.
    fail_closed: bool = True
    max_data_age_hours: int = 24


@dataclass(frozen=True)
class ApiCredentials:
    crypto_api_key: Secret = field(default_factory=lambda: Secret(""))
    crypto_api_secret: Secret = field(default_factory=lambda: Secret(""))
    futures_api_key: Secret = field(default_factory=lambda: Secret(""))
    futures_api_secret: Secret = field(default_factory=lambda: Secret(""))


@dataclass(frozen=True)
class Settings:
    environment: Environment
    accounts: tuple[AccountConfig, ...]
    risk: RiskLimits
    session: SessionConfig
    news: NewsConfig
    credentials: ApiCredentials
    log_level: str = "INFO"
    log_dir: Path = PACKAGE_DIR / "logs"
    state_db_path: Path = PACKAGE_DIR / "state" / "bot_state.db"


# --------------------------------------------------------------------- .env
def load_dotenv(path: Path) -> None:
    """Minimal .env loader. Real environment variables always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


# ------------------------------------------------------------------ parsing
class _Reader:
    """Reads typed values from an env mapping, collecting every error."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env
        self.errors: list[str] = []

    def raw(self, name: str, default: str = "") -> str:
        return self.env.get(name, "").strip() or default

    def _parse(self, name: str, default: T, parse: Callable[[str], T], kind: str) -> T:
        raw = self.raw(name)
        if not raw:
            return default
        try:
            return parse(raw)
        except (ValueError, KeyError):
            self.errors.append(f"{name}={raw!r} is not a valid {kind}")
            return default

    def float_(self, name: str, default: float, *, lo: float, hi: float) -> float:
        value = self._parse(name, default, float, "number")
        if not lo < value <= hi:
            self.errors.append(f"{name}={value} must be in ({lo}, {hi}]")
        return value

    def int_(self, name: str, default: int, *, lo: int) -> int:
        value = self._parse(name, default, int, "integer")
        if value < lo:
            self.errors.append(f"{name}={value} must be >= {lo}")
        return value

    def bool_(self, name: str, default: bool) -> bool:
        raw = self.raw(name).lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        self.errors.append(f"{name}={raw!r} is not a boolean")
        return default

    def enum_(self, name: str, default: T, enum_type: Callable[[str], T]) -> T:
        return self._parse(name, default, lambda v: enum_type(v.lower()), "choice")

    def list_(self, name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        raw = self.raw(name)
        if not raw:
            return default
        return tuple(item.strip() for item in raw.split(",") if item.strip())

    def path(self, name: str, default: Path) -> Path:
        raw = self.raw(name)
        if not raw:
            return default
        path = Path(raw).expanduser()
        return path if path.is_absolute() else PACKAGE_DIR / path


_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _parse_accounts(reader: _Reader) -> tuple[AccountConfig, ...]:
    raw = reader.raw("ACCOUNTS")
    if not raw:
        reader.errors.append("ACCOUNTS is required, e.g. ACCOUNTS=ftmo_1:100000,apex_1:50000")
        return ()
    accounts: list[AccountConfig] = []
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        account_id, sep, balance = entry.partition(":")
        account_id = account_id.strip()
        if not sep or not _ACCOUNT_ID.match(account_id):
            reader.errors.append(f"ACCOUNTS entry {entry!r} must look like <id>:<initial_balance>")
            continue
        try:
            initial = float(balance)
        except ValueError:
            reader.errors.append(f"ACCOUNTS entry {entry!r} has a non-numeric balance")
            continue
        if initial <= 0:
            reader.errors.append(f"ACCOUNTS entry {entry!r} must have a positive balance")
            continue
        if any(a.account_id == account_id for a in accounts):
            reader.errors.append(f"ACCOUNTS lists {account_id!r} twice")
            continue
        accounts.append(AccountConfig(account_id, initial))
    return tuple(accounts)


def _parse_session(reader: _Reader) -> SessionConfig:
    tz_name = reader.raw("DAILY_RESET_TZ", "America/New_York")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        reader.errors.append(f"DAILY_RESET_TZ={tz_name!r} is not a known time zone")
        tz = ZoneInfo("UTC")
    reset_raw = reader.raw("DAILY_RESET_TIME", "17:00")
    try:
        reset = time.fromisoformat(reset_raw)
    except ValueError:
        reader.errors.append(f"DAILY_RESET_TIME={reset_raw!r} must be HH:MM")
        reset = time(17, 0)
    return SessionConfig(reset_tz=tz, reset_time=reset)


def settings_from_env(env: Mapping[str, str]) -> Settings:
    """Build and validate :class:`Settings` from an environment mapping."""
    r = _Reader(env)

    risk = RiskLimits(
        daily_loss_limit_pct=r.float_("DAILY_LOSS_LIMIT_PCT", 1.5, lo=0, hi=100),
        daily_loss_basis=r.enum_("DAILY_LOSS_BASIS", DailyLossBasis.INITIAL, DailyLossBasis),
        max_drawdown_pct=r.float_("MAX_DRAWDOWN_PCT", 5.0, lo=0, hi=100),
        max_drawdown_mode=r.enum_("MAX_DRAWDOWN_MODE", DrawdownMode.TRAILING_INTRADAY, DrawdownMode),
        drawdown_lock_at_initial=r.bool_("DRAWDOWN_LOCK_AT_INITIAL", True),
        risk_per_trade_pct=r.float_("RISK_PER_TRADE_PCT", 0.5, lo=0, hi=10),
        max_trades_per_day=r.int_("MAX_TRADES_PER_DAY", 5, lo=1),
        equity_stale_seconds=r.int_("EQUITY_STALE_SECONDS", 120, lo=1),
        room_usage_fraction=r.float_("ROOM_USAGE_FRACTION", 0.8, lo=0, hi=1),
    )
    if risk.risk_per_trade_pct > risk.daily_loss_limit_pct:
        r.errors.append("RISK_PER_TRADE_PCT must not exceed DAILY_LOSS_LIMIT_PCT")
    if risk.daily_loss_limit_pct > risk.max_drawdown_pct:
        r.errors.append("DAILY_LOSS_LIMIT_PCT must not exceed MAX_DRAWDOWN_PCT")

    news_source = r.enum_("NEWS_CALENDAR_SOURCE", NewsSource.FOREXFACTORY, NewsSource)
    news_file_raw = r.raw("NEWS_CALENDAR_FILE")
    news = NewsConfig(
        source=news_source,
        url=r.raw("NEWS_CALENDAR_URL", NewsConfig.url),
        file=r.path("NEWS_CALENDAR_FILE", PACKAGE_DIR) if news_file_raw else None,
        cache_file=r.path("NEWS_CALENDAR_CACHE", NewsConfig().cache_file),
        minutes_before=r.int_("NEWS_BLACKOUT_MINUTES_BEFORE", 15, lo=0),
        minutes_after=r.int_("NEWS_BLACKOUT_MINUTES_AFTER", 15, lo=0),
        currencies=tuple(c.upper() for c in r.list_("NEWS_CURRENCIES", ("USD",))),
        keywords=r.list_("NEWS_KEYWORDS", NewsConfig().keywords),
        refresh_minutes=r.int_("NEWS_CALENDAR_REFRESH_MINUTES", 360, lo=5),
        fail_closed=r.bool_("NEWS_FAIL_CLOSED", True),
        max_data_age_hours=r.int_("NEWS_MAX_DATA_AGE_HOURS", 24, lo=1),
    )
    if news.source is NewsSource.FILE and news.file is None:
        r.errors.append("NEWS_CALENDAR_SOURCE=file requires NEWS_CALENDAR_FILE")

    log_level = r.raw("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        r.errors.append(f"LOG_LEVEL={log_level!r} is not a logging level")

    settings = Settings(
        environment=r.enum_("ENVIRONMENT", Environment.PAPER, Environment),
        accounts=_parse_accounts(r),
        risk=risk,
        session=_parse_session(r),
        news=news,
        credentials=ApiCredentials(
            crypto_api_key=Secret(r.raw("CRYPTO_API_KEY")),
            crypto_api_secret=Secret(r.raw("CRYPTO_API_SECRET")),
            futures_api_key=Secret(r.raw("FUTURES_API_KEY")),
            futures_api_secret=Secret(r.raw("FUTURES_API_SECRET")),
        ),
        log_level=log_level,
        log_dir=r.path("LOG_DIR", PACKAGE_DIR / "logs"),
        state_db_path=r.path("STATE_DB_PATH", PACKAGE_DIR / "state" / "bot_state.db"),
    )
    if r.errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(r.errors))
    return settings


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Load ``env_file`` into the process environment, then build settings."""
    if env_file is not None:
        load_dotenv(env_file)
    return settings_from_env(os.environ)
