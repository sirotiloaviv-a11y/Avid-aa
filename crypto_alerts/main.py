"""Entry point: wires market data → indicators → strategy → risk → Telegram.

Run with ``python -m crypto_alerts``. One asyncio task per symbol consumes the
closed-candle stream; one dispatcher task delivers alerts. A failure while
evaluating one candle is logged and skipped, a network failure is retried
inside the feed, and only an unrecoverable error on a symbol (e.g. it was
delisted) stops that symbol — the others keep running.
"""

from __future__ import annotations

import asyncio
import html
import logging
import signal
import sys
from typing import Optional, Sequence

from .config import ConfigError, Settings
from .indicators import compute_indicators
from .market_data import Candle, FatalFeedError, MarketDataFeed
from .risk_manager import RiskError, RiskManager, TradePlan
from .strategy import Direction, RsiVolumeReversalStrategy, Strategy
from .telegram_bot import AlertDispatcher, create_notifier, format_alert, format_startup

log = logging.getLogger("crypto_alerts")


class Cooldown:
    """Suppresses repeat alerts for the same symbol and direction.

    Keyed on candle time rather than wall-clock time, so it behaves the same
    live, after a reconnect backfill, and in tests.
    """

    def __init__(self, minutes: float) -> None:
        self._window_ms = int(minutes * 60_000)
        self._last: dict[tuple[str, Direction], int] = {}

    def allow(self, symbol: str, direction: Direction, candle_ts: int) -> bool:
        key = (symbol, direction)
        previous = self._last.get(key)
        if previous is not None and candle_ts - previous < self._window_ms:
            return False
        self._last[key] = candle_ts
        return True


class AlertEngine:
    def __init__(
        self,
        settings: Settings,
        feed: MarketDataFeed,
        strategy: Strategy,
        risk_manager: RiskManager,
        dispatcher: AlertDispatcher,
    ) -> None:
        self.settings = settings
        self.feed = feed
        self.strategy = strategy
        self.risk = risk_manager
        self.dispatcher = dispatcher
        self.cooldown = Cooldown(settings.alert_cooldown_minutes)

    def process(self, symbol: str, candles: Sequence[Candle]) -> Optional[TradePlan]:
        """Evaluate the latest closed candle; enqueue and return a plan if it triggers."""
        if not candles:
            return None
        if self.feed.is_stale(candles[-1]):
            log.debug("%s: skipping stale candle %s", symbol, candles[-1].timestamp)
            return None
        frame = compute_indicators(candles, self.settings.indicators)
        signal_ = self.strategy.evaluate(symbol, self.settings.exchange.timeframe, frame)
        if signal_ is None:
            last = frame.last
            log.debug(
                "%s close=%s rsi=%s vol_x=%s — no signal",
                symbol, candles[-1].close, _round(frame.rsi[last]), _round(frame.volume_ratio[last]),
            )
            return None
        if not self.cooldown.allow(symbol, signal_.direction, signal_.candle.timestamp):
            log.info("%s %s signal suppressed by cooldown", symbol, signal_.direction.value)
            return None
        try:
            plan = self.risk.build_plan(signal_, lambda units: self.feed.round_amount(symbol, units))
        except RiskError as exc:
            log.warning("%s %s signal discarded: %s", symbol, signal_.direction.value, exc)
            return None
        log.info(
            "ALERT %s %s entry=%s sl=%s tp=%s units=%.8g risk=$%.2f",
            signal_.direction.value, symbol, plan.entry, plan.stop_loss, plan.take_profit,
            plan.units, plan.risk_amount,
        )
        self.dispatcher.enqueue(format_alert(plan, self.feed.timeframe_ms))
        return plan

    async def watch_symbol(self, symbol: str) -> None:
        try:
            async for candles in self.feed.stream_closed_candles(symbol):
                try:
                    self.process(symbol, candles)
                except Exception:
                    log.exception("%s: error while evaluating candle — skipped", symbol)
        except FatalFeedError as exc:
            log.error("Stopped monitoring %s: %s", symbol, exc)
            self.dispatcher.enqueue(
                f"⚠️ Stopped monitoring <b>{html.escape(symbol)}</b>: {html.escape(str(exc))}"
            )


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


async def run(settings: Settings) -> None:
    feed = MarketDataFeed(settings.exchange)
    notifier = create_notifier(settings)
    dispatcher = AlertDispatcher(notifier)
    engine = AlertEngine(
        settings,
        feed,
        RsiVolumeReversalStrategy(settings.strategy),
        RiskManager(settings.risk),
        dispatcher,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows
            pass

    dispatcher_task = asyncio.create_task(dispatcher.run(), name="dispatcher")
    tasks: list[asyncio.Task] = []
    try:
        symbols = await feed.connect()
        if not symbols:
            raise FatalFeedError("none of the configured SYMBOLS exist on the exchange")
        if settings.telegram.send_startup_message:
            dispatcher.enqueue(format_startup(settings, symbols, feed.streaming))
        tasks = [asyncio.create_task(engine.watch_symbol(s), name=f"watch:{s}") for s in symbols]
        stopper = asyncio.create_task(stop.wait(), name="stop")
        watchers = asyncio.gather(*tasks)
        # Return when asked to stop, or when every symbol has stopped for good.
        done, _ = await asyncio.wait({stopper, watchers}, return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
        if watchers in done:
            watchers.result()  # surface anything unexpected
            log.error("Every symbol has stopped; exiting")
    finally:
        log.info("Shutting down")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispatcher.drain()
        dispatcher_task.cancel()
        await asyncio.gather(dispatcher_task, return_exceptions=True)
        await feed.close()
        close = getattr(notifier, "close", None)
        if close is not None:
            await close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # httpx logs every Telegram request at INFO, which buries the useful lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(run(settings))
    except FatalFeedError as exc:
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
