"""Settings, loaded from environment variables (and an optional .env file).

Every tunable lives here so the other modules stay pure: they receive a frozen
settings object and never read the environment themselves. That keeps them
trivially testable and means a typo in .env fails loudly at startup instead of
silently mid-session.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

BASE_DIR = Path(__file__).resolve().parent

STOP_MODES = ("atr", "swing", "hybrid")
LIQUIDITY_ACTIONS = ("warn", "reduce", "filter")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
MARKET_TYPES = ("spot", "swap", "future", "margin")


class ConfigError(ValueError):
    """Raised when one or more settings are missing or invalid."""


def load_dotenv(path: Path) -> None:
    """Minimal .env loader. No dependency, and never overwrites real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


class _Env:
    """Typed reads from an environment mapping that collect every error.

    Collecting instead of raising on the first problem means one startup run
    reports everything that is wrong with the .env file.
    """

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ
        self.errors: list[str] = []

    def _raw(self, name: str) -> str | None:
        value = self._environ.get(name)
        if value is None or not value.strip():
            return None
        return value.strip()

    def str(self, name: str, default: str = "") -> str:
        raw = self._raw(name)
        return default if raw is None else raw

    def float(
        self,
        name: str,
        default: float,
        *,
        gt: float | None = None,
        ge: float | None = None,
        le: float | None = None,
    ) -> float:
        raw = self._raw(name)
        if raw is None:
            return default
        try:
            value = float(raw.replace("_", "").replace(",", "").rstrip("%"))
        except ValueError:
            self.errors.append(f"{name}={raw!r} is not a number")
            return default
        if gt is not None and not value > gt:
            self.errors.append(f"{name}={value} must be > {gt}")
        if ge is not None and not value >= ge:
            self.errors.append(f"{name}={value} must be >= {ge}")
        if le is not None and not value <= le:
            self.errors.append(f"{name}={value} must be <= {le}")
        return value

    def int(self, name: str, default: int, *, ge: int | None = None) -> int:
        raw = self._raw(name)
        if raw is None:
            return default
        try:
            value = int(raw.replace("_", ""))
        except ValueError:
            self.errors.append(f"{name}={raw!r} is not an integer")
            return default
        if ge is not None and value < ge:
            self.errors.append(f"{name}={value} must be >= {ge}")
        return value

    def bool(self, name: str, default: bool) -> bool:
        raw = self._raw(name)
        if raw is None:
            return default
        lowered = raw.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        self.errors.append(f"{name}={raw!r} is not a boolean (use true/false)")
        return default

    def list(self, name: str, default: tuple[str, ...]) -> tuple[str, ...]:
        raw = self._raw(name)
        if raw is None:
            return default
        items = tuple(item.strip() for item in raw.replace("\n", ",").split(",") if item.strip())
        return items or default

    def choice(self, name: str, default: str, choices: tuple[str, ...]) -> str:
        value = self.str(name, default).lower()
        if value not in choices:
            self.errors.append(f"{name}={value!r} must be one of {', '.join(choices)}")
            return default
        return value


@dataclass(frozen=True)
class ExchangeSettings:
    exchange_id: str = "binance"
    # "spot" or "swap" (perpetuals). Perp symbols use ccxt's unified form,
    # e.g. "BTC/USDT:USDT".
    market_type: str = "spot"
    symbols: tuple[str, ...] = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    timeframe: str = "15m"
    use_websocket: bool = True
    poll_interval_seconds: float = 15.0
    # A websocket that has been silent this long is treated as dead and the
    # feed reconnects (with a fresh REST backfill).
    stream_timeout_seconds: float = 120.0
    history_candles: int = 300
    # Optional. Market data is public; keys only raise rate limits. Use
    # read-only keys — this system never places orders.
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    sandbox: bool = False


@dataclass(frozen=True)
class IndicatorSettings:
    rsi_period: int = 14
    atr_period: int = 14
    volume_ma_period: int = 20
    fast_ma_period: int = 50
    slow_ma_period: int = 200
    # A swing low/high is a candle whose low/high is the extreme of the
    # `swing_width` candles on each side of it.
    swing_width: int = 3


@dataclass(frozen=True)
class StrategySettings:
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    # How many of the most recent closed candles may satisfy the RSI condition.
    # 1 means the signal candle itself must be oversold/overbought.
    rsi_lookback: int = 1
    volume_spike_multiplier: float = 2.5
    # How far back (in candles) to look for swing levels acting as S/R.
    sr_lookback: int = 100
    # How close (in ATRs) the wick must come to a level to count as a test.
    sr_tolerance_atr: float = 0.5
    # When true, longs need close > slow MA and shorts close < slow MA.
    trend_filter: bool = False
    # Conviction factors (see strategy.py): RSI this many points beyond the
    # threshold, and volume this many times the spike multiplier.
    extreme_rsi_margin: float = 10.0
    extreme_volume_factor: float = 2.0


@dataclass(frozen=True)
class RiskSettings:
    account_equity: float = 1_000_000.0
    # In percent: 0.5 means 0.5% of equity is lost if the stop is hit.
    risk_per_trade_pct: float = 0.5
    risk_reward_ratio: float = 2.5
    stop_mode: str = "hybrid"
    atr_stop_multiplier: float = 1.5
    swing_buffer_atr: float = 0.2
    min_stop_atr: float = 0.5
    max_stop_atr: float = 3.0
    # Notional is capped at equity * max_leverage. When the cap binds, the
    # trade risks less than the budget and the alert says so.
    max_leverage: float = 3.0
    # Taker fee in percent per side (e.g. 0.055 on Bybit). When > 0 the
    # position is sized so price loss + both fees equals the risk budget.
    fee_rate_pct: float = 0.0
    # Width of the entry zone in ATRs, on the favourable side of the signal
    # price only — filling anywhere in it never risks more than the budget.
    entry_zone_atr: float = 0.15

    @property
    def risk_budget(self) -> float:
        return self.account_equity * self.risk_per_trade_pct / 100.0


@dataclass(frozen=True)
class LiquiditySettings:
    enabled: bool = True
    # warn   — send the alert with a slippage warning
    # reduce — shrink the size to what the book absorbs within the threshold
    # filter — drop the alert
    action: str = "warn"
    # Expected fill vs mid price, in percent. 0.1 means 0.1%.
    max_slippage_pct: float = 0.1
    # Order book levels fetched per side at alert time.
    depth_limit: int = 100


@dataclass(frozen=True)
class UrgentSettings:
    enabled: bool = True
    # An alert is urgent (high conviction) when it has at least this many
    # conviction factors and the liquidity check passed.
    min_factors: int = 2
    # Pushover (https://pushover.net). Both token and user key are needed.
    pushover_token: str = field(default="", repr=False)
    pushover_user: str = field(default="", repr=False)
    # -2 lowest ... 1 high (bypasses quiet hours) ... 2 emergency (repeats until acknowledged)
    pushover_priority: int = 1
    pushover_sound: str = "cashregister"
    pushover_urgent_only: bool = True
    # Local sound, e.g. "afplay /System/Library/Sounds/Glass.aiff" or
    # "paplay /usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga".
    # Empty = no local sound.
    sound_command: str = ""
    sound_urgent_only: bool = True

    @property
    def pushover_enabled(self) -> bool:
        return bool(self.pushover_token and self.pushover_user)


@dataclass(frozen=True)
class DashboardSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8765
    # Required when host is not loopback. Open /?token=... once to log in.
    token: str = field(default="", repr=False)


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str = field(default="", repr=False)
    chat_id: str = ""
    # Print alerts to stdout instead of sending them. Useful for a first run.
    dry_run: bool = False
    send_startup_message: bool = True
    # A second chat that receives only urgent alerts. Give it its own
    # notification sound in the Telegram app — bots cannot choose sounds.
    urgent_chat_id: str = ""
    # Deliver normal alerts silently so only urgent ones make a sound.
    quiet_normal_alerts: bool = False


@dataclass(frozen=True)
class Settings:
    exchange: ExchangeSettings = field(default_factory=ExchangeSettings)
    indicators: IndicatorSettings = field(default_factory=IndicatorSettings)
    strategy: StrategySettings = field(default_factory=StrategySettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    liquidity: LiquiditySettings = field(default_factory=LiquiditySettings)
    urgent: UrgentSettings = field(default_factory=UrgentSettings)
    dashboard: DashboardSettings = field(default_factory=DashboardSettings)
    # Suppress repeat alerts for the same symbol and direction for this long.
    alert_cooldown_minutes: float = 60.0
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        dotenv_path: Path | None = BASE_DIR / ".env",
    ) -> "Settings":
        """Build settings from the environment. Raises ConfigError listing every problem."""
        if environ is None:
            if dotenv_path is not None:
                load_dotenv(dotenv_path)
            environ = os.environ
        env = _Env(environ)

        exchange = ExchangeSettings(
            exchange_id=env.str("EXCHANGE_ID", "binance").lower(),
            market_type=env.choice("MARKET_TYPE", "spot", MARKET_TYPES),
            symbols=env.list("SYMBOLS", ExchangeSettings.symbols),
            timeframe=env.str("TIMEFRAME", "15m"),
            use_websocket=env.bool("USE_WEBSOCKET", True),
            poll_interval_seconds=env.float("POLL_INTERVAL_SECONDS", 15.0, ge=1.0),
            stream_timeout_seconds=env.float("STREAM_TIMEOUT_SECONDS", 120.0, ge=10.0),
            history_candles=env.int("HISTORY_CANDLES", 300, ge=50),
            api_key=env.str("EXCHANGE_API_KEY"),
            api_secret=env.str("EXCHANGE_API_SECRET"),
            sandbox=env.bool("EXCHANGE_SANDBOX", False),
        )
        indicators = IndicatorSettings(
            rsi_period=env.int("RSI_PERIOD", 14, ge=2),
            atr_period=env.int("ATR_PERIOD", 14, ge=2),
            volume_ma_period=env.int("VOLUME_MA_PERIOD", 20, ge=2),
            fast_ma_period=env.int("FAST_MA_PERIOD", 50, ge=2),
            slow_ma_period=env.int("SLOW_MA_PERIOD", 200, ge=2),
            swing_width=env.int("SWING_WIDTH", 3, ge=1),
        )
        strategy = StrategySettings(
            rsi_oversold=env.float("RSI_OVERSOLD", 30.0, gt=0, le=100),
            rsi_overbought=env.float("RSI_OVERBOUGHT", 70.0, gt=0, le=100),
            rsi_lookback=env.int("RSI_LOOKBACK", 1, ge=1),
            volume_spike_multiplier=env.float("VOLUME_SPIKE_MULTIPLIER", 2.5, gt=0),
            sr_lookback=env.int("SR_LOOKBACK", 100, ge=10),
            sr_tolerance_atr=env.float("SR_TOLERANCE_ATR", 0.5, gt=0),
            trend_filter=env.bool("TREND_FILTER", False),
            extreme_rsi_margin=env.float("EXTREME_RSI_MARGIN", 10.0, ge=0),
            extreme_volume_factor=env.float("EXTREME_VOLUME_FACTOR", 2.0, ge=1),
        )
        risk = RiskSettings(
            account_equity=env.float("ACCOUNT_EQUITY", 1_000_000.0, gt=0),
            risk_per_trade_pct=env.float("RISK_PER_TRADE_PCT", 0.5, gt=0, le=100),
            risk_reward_ratio=env.float("RISK_REWARD_RATIO", 2.5, gt=0),
            stop_mode=env.choice("STOP_MODE", "hybrid", STOP_MODES),
            atr_stop_multiplier=env.float("ATR_STOP_MULTIPLIER", 1.5, gt=0),
            swing_buffer_atr=env.float("SWING_BUFFER_ATR", 0.2, ge=0),
            min_stop_atr=env.float("MIN_STOP_ATR", 0.5, gt=0),
            max_stop_atr=env.float("MAX_STOP_ATR", 3.0, gt=0),
            max_leverage=env.float("MAX_LEVERAGE", 3.0, gt=0),
            fee_rate_pct=env.float("FEE_RATE_PCT", 0.0, ge=0, le=5),
            entry_zone_atr=env.float("ENTRY_ZONE_ATR", 0.15, ge=0),
        )
        telegram = TelegramSettings(
            bot_token=env.str("TELEGRAM_BOT_TOKEN"),
            chat_id=env.str("TELEGRAM_CHAT_ID"),
            dry_run=env.bool("DRY_RUN", False),
            send_startup_message=env.bool("SEND_STARTUP_MESSAGE", True),
            urgent_chat_id=env.str("TELEGRAM_URGENT_CHAT_ID"),
            quiet_normal_alerts=env.bool("TELEGRAM_QUIET_NORMAL_ALERTS", False),
        )
        liquidity = LiquiditySettings(
            enabled=env.bool("LIQUIDITY_CHECK", True),
            action=env.choice("LIQUIDITY_ACTION", "warn", LIQUIDITY_ACTIONS),
            max_slippage_pct=env.float("MAX_SLIPPAGE_PCT", 0.1, gt=0, le=10),
            depth_limit=env.int("ORDER_BOOK_DEPTH", 100, ge=5),
        )
        urgent = UrgentSettings(
            enabled=env.bool("URGENT_ALERTS", True),
            min_factors=env.int("URGENT_MIN_FACTORS", 2, ge=1),
            pushover_token=env.str("PUSHOVER_APP_TOKEN"),
            pushover_user=env.str("PUSHOVER_USER_KEY"),
            pushover_priority=env.int("PUSHOVER_PRIORITY", 1, ge=-2),
            pushover_sound=env.str("PUSHOVER_SOUND", "cashregister"),
            pushover_urgent_only=env.bool("PUSHOVER_URGENT_ONLY", True),
            sound_command=env.str("SOUND_COMMAND"),
            sound_urgent_only=env.bool("SOUND_URGENT_ONLY", True),
        )
        dashboard = DashboardSettings(
            enabled=env.bool("DASHBOARD_ENABLED", True),
            host=env.str("DASHBOARD_HOST", "127.0.0.1"),
            port=env.int("DASHBOARD_PORT", 8765, ge=0),
            token=env.str("DASHBOARD_TOKEN"),
        )
        settings = cls(
            exchange=exchange,
            indicators=indicators,
            strategy=strategy,
            risk=risk,
            telegram=telegram,
            liquidity=liquidity,
            urgent=urgent,
            dashboard=dashboard,
            alert_cooldown_minutes=env.float("ALERT_COOLDOWN_MINUTES", 60.0, ge=0),
            log_level=env.str("LOG_LEVEL", "INFO").upper(),
        )
        errors = env.errors + settings.validate()
        if errors:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))
        return settings

    def validate(self) -> list[str]:
        """Cross-field checks that a single typed read cannot catch."""
        errors: list[str] = []
        if not self.telegram.dry_run:
            if not self.telegram.bot_token:
                errors.append("TELEGRAM_BOT_TOKEN is required (or set DRY_RUN=true)")
            if not self.telegram.chat_id:
                errors.append("TELEGRAM_CHAT_ID is required (or set DRY_RUN=true)")
        if not self.exchange.symbols:
            errors.append("SYMBOLS must list at least one market")
        if self.strategy.rsi_oversold >= self.strategy.rsi_overbought:
            errors.append("RSI_OVERSOLD must be below RSI_OVERBOUGHT")
        if self.risk.min_stop_atr > self.risk.max_stop_atr:
            errors.append("MIN_STOP_ATR must not exceed MAX_STOP_ATR")
        if self.risk.risk_per_trade_pct > 5:
            errors.append(
                f"RISK_PER_TRADE_PCT={self.risk.risk_per_trade_pct} is a percentage "
                "(0.5 means 0.5%); values above 5 are rejected as a likely typo"
            )
        needed = self.min_history()
        if self.exchange.history_candles < needed:
            errors.append(
                f"HISTORY_CANDLES={self.exchange.history_candles} is too short for the "
                f"configured indicators; need at least {needed}"
            )
        try:
            parse_timeframe(self.exchange.timeframe)
        except ValueError as exc:
            errors.append(str(exc))
        u = self.urgent
        if bool(u.pushover_token) != bool(u.pushover_user):
            errors.append("PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY must be set together")
        if u.pushover_priority > 2:
            errors.append(f"PUSHOVER_PRIORITY={u.pushover_priority} must be between -2 and 2")
        d = self.dashboard
        if d.enabled and d.host not in LOOPBACK_HOSTS and not d.token:
            errors.append(
                f"DASHBOARD_HOST={d.host} exposes a page that can change position sizing; "
                "set DASHBOARD_TOKEN or bind to 127.0.0.1"
            )
        if d.port > 65535:
            errors.append(f"DASHBOARD_PORT={d.port} is not a valid port")
        return errors

    def min_history(self) -> int:
        ind, strat = self.indicators, self.strategy
        return (
            max(
                ind.slow_ma_period,
                ind.fast_ma_period,
                ind.rsi_period + 1,
                ind.atr_period + 1,
                ind.volume_ma_period + 1,
                strat.sr_lookback,
            )
            + ind.swing_width
            + 1
        )


_TIMEFRAME_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000}


def parse_timeframe(timeframe: str) -> int:
    """Return a ccxt timeframe string such as "15m" or "4h" in seconds."""
    amount, unit = timeframe[:-1], timeframe[-1:]
    if not amount.isdigit() or unit not in _TIMEFRAME_SECONDS or int(amount) <= 0:
        raise ValueError(f"TIMEFRAME={timeframe!r} is not a valid timeframe (e.g. 5m, 15m, 1h)")
    return int(amount) * _TIMEFRAME_SECONDS[unit]
