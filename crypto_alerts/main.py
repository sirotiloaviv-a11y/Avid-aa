"""Entry point: wires market data → indicators → strategy → risk → liquidity → channels.

Run with ``python -m crypto_alerts``. One asyncio task per symbol consumes the
closed-candle stream, one dispatcher task delivers alerts to every channel,
and the dashboard (if enabled) serves the runtime state from the same process,
so risk changes made there apply to the very next alert.

A failure while evaluating one candle is logged and skipped, a network failure
is retried inside the feed, and only an unrecoverable error on a symbol (e.g.
it was delisted) stops that symbol — the others keep running.
"""

from __future__ import annotations

import asyncio
import dataclasses
import html
import logging
import signal
import sys
from typing import Optional, Sequence

from .config import ConfigError, Settings
from .indicators import compute_indicators
from .market_data import Candle, FatalFeedError, MarketDataFeed
from .notifiers import AlertDispatcher, Channel, ConsoleChannel, Notification, PushoverChannel, SoundChannel
from .risk_manager import RiskError, RiskManager, TradePlan
from .state import RuntimeState
from .strategy import Direction, RsiVolumeReversalStrategy, Strategy
from .telegram_bot import (
    TelegramNotifier,
    alert_title,
    format_alert,
    format_push,
    format_risk_change,
    format_startup,
)

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
        state: Optional[RuntimeState] = None,
    ) -> None:
        self.settings = settings
        self.feed = feed
        self.strategy = strategy
        self.risk = risk_manager
        self.dispatcher = dispatcher
        self.state = state or RuntimeState()
        self.cooldown = Cooldown(settings.alert_cooldown_minutes)

    async def process(self, symbol: str, candles: Sequence[Candle]) -> Optional[TradePlan]:
        """Evaluate the latest closed candle; enqueue and return a plan if it triggers."""
        if not candles:
            return None
        if self.feed.is_stale(candles[-1]):
            log.debug("%s: skipping stale candle %s", symbol, candles[-1].timestamp)
            return None
        frame = compute_indicators(candles, self.settings.indicators)
        last = frame.last
        self.state.record_evaluation(symbol, candles[-1], frame.rsi[last], frame.volume_ratio[last], frame.atr[last])
        signal_ = self.strategy.evaluate(symbol, self.settings.exchange.timeframe, frame)
        if signal_ is None:
            log.debug(
                "%s close=%s rsi=%s vol_x=%s — no signal",
                symbol, candles[-1].close, _round(frame.rsi[last]), _round(frame.volume_ratio[last]),
            )
            return None
        direction = signal_.direction.value
        if not self.cooldown.allow(symbol, signal_.direction, signal_.candle.timestamp):
            log.info("%s %s signal suppressed by cooldown", symbol, direction)
            self.state.record_alert(None, symbol=symbol, direction=direction, status="suppressed",
                                    note="cooldown")
            return None

        rounder = lambda units: self.feed.round_amount(symbol, units)  # noqa: E731
        try:
            plan = self.risk.build_plan(signal_, rounder)
        except RiskError as exc:
            log.warning("%s %s signal discarded: %s", symbol, direction, exc)
            self.state.record_alert(None, symbol=symbol, direction=direction, status="discarded", note=str(exc))
            return None

        plan = await self._liquidity_guard(plan, rounder)
        if plan.liquidity_action == "filtered":
            liq = plan.liquidity
            note = (
                f"slippage {liq.slippage_pct:.3f}% > {liq.threshold_pct:g}%"
                if liq is not None and liq.fully_filled else "order book too thin for the size"
            )
            log.info("%s %s alert filtered by liquidity guard: %s", symbol, direction, note)
            self.state.record_alert(plan, symbol=symbol, direction=direction, status="filtered", note=note)
            return None

        urgent = self.is_urgent(plan)
        log.info(
            "ALERT%s %s %s entry=%s sl=%s tp=%s units=%.8g risk=$%.2f liquidity=%s",
            " [URGENT]" if urgent else "", direction, symbol, plan.entry, plan.stop_loss,
            plan.take_profit, plan.units, plan.risk_amount, plan.liquidity_action,
        )
        self.dispatcher.enqueue(Notification(
            text=format_alert(plan, self.feed.timeframe_ms, urgent=urgent),
            title=alert_title(plan, urgent),
            short_text=format_push(plan),
            urgent=urgent,
        ))
        self.state.record_alert(plan, symbol=symbol, direction=direction, status="sent", urgent=urgent)
        return plan

    async def _liquidity_guard(self, plan: TradePlan, rounder) -> TradePlan:
        liq = self.settings.liquidity
        if not liq.enabled:
            return plan
        try:
            book = await asyncio.wait_for(self.feed.fetch_order_book(plan.symbol, liq.depth_limit), timeout=10)
            return self.risk.apply_liquidity(plan, book, liq, rounder)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A missing book must not suppress a valid alert; flag it instead.
            reason = "timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
            log.warning("%s: order book check failed (%r) — sending alert unchecked", plan.symbol, exc)
            return dataclasses.replace(plan, liquidity_error=reason)

    def is_urgent(self, plan: TradePlan) -> bool:
        """High conviction: enough conviction factors and a liquidity check that did not warn."""
        u = self.settings.urgent
        if not u.enabled or len(plan.signal.conviction_factors) < u.min_factors:
            return False
        if self.settings.liquidity.enabled and plan.liquidity_action not in ("ok", "reduced"):
            return False
        return True

    def update_risk(self, account_equity: Optional[float], risk_per_trade_pct: Optional[float],
                    source: str = "dashboard") -> dict[str, float]:
        """Change equity / risk % live. Raises RiskError on invalid values. Announced on Telegram."""
        old = self.risk.settings
        new = self.risk.update_account(account_equity, risk_per_trade_pct)
        before = {"account_equity": old.account_equity, "risk_per_trade_pct": old.risk_per_trade_pct}
        after = {"account_equity": new.account_equity, "risk_per_trade_pct": new.risk_per_trade_pct}
        if before != after:
            log.warning("Risk settings changed via %s: %s -> %s", source, before, after)
            self.state.record_risk_change(before, after, source)
            self.dispatcher.enqueue(Notification(
                text=format_risk_change(old.account_equity, old.risk_per_trade_pct,
                                        new.account_equity, new.risk_per_trade_pct, source),
                title="Risk settings changed",
                kind="system",
            ))
        return after

    async def watch_symbol(self, symbol: str) -> None:
        try:
            async for candles in self.feed.stream_closed_candles(symbol):
                try:
                    await self.process(symbol, candles)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("%s: error while evaluating candle — skipped", symbol)
        except FatalFeedError as exc:
            log.error("Stopped monitoring %s: %s", symbol, exc)
            self.state.on_feed_state(symbol, "stopped", str(exc))
            self.dispatcher.enqueue(
                f"⚠️ Stopped monitoring <b>{html.escape(symbol)}</b>: {html.escape(str(exc))}"
            )


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def build_channels(settings: Settings) -> list[Channel]:
    """Every configured notification channel."""
    channels: list[Channel] = []
    t, u = settings.telegram, settings.urgent
    if t.dry_run:
        channels.append(ConsoleChannel())
    else:
        channels.append(TelegramNotifier(
            t.bot_token, t.chat_id,
            urgent_chat_id=t.urgent_chat_id,
            quiet_normal_alerts=t.quiet_normal_alerts,
        ))
    if u.pushover_enabled:
        channels.append(PushoverChannel(
            u.pushover_token, u.pushover_user,
            priority=u.pushover_priority, sound=u.pushover_sound, urgent_only=u.pushover_urgent_only,
        ))
    if u.sound_command or t.dry_run:
        channels.append(SoundChannel(u.sound_command, urgent_only=u.sound_urgent_only))
    return channels


async def run(settings: Settings) -> None:
    state = RuntimeState(settings.exchange.symbols)
    feed = MarketDataFeed(settings.exchange, listener=state)
    channels = build_channels(settings)
    dispatcher = AlertDispatcher(channels)
    engine = AlertEngine(
        settings,
        feed,
        RsiVolumeReversalStrategy(settings.strategy),
        RiskManager(settings.risk),
        dispatcher,
        state,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows
            pass

    background = [asyncio.create_task(dispatcher.run(), name="dispatcher")]
    if settings.dashboard.enabled:
        from .dashboard import DashboardServer

        server = DashboardServer(engine, settings.dashboard)
        background.append(asyncio.create_task(server.run(stop), name="dashboard"))

    tasks: list[asyncio.Task] = []
    try:
        symbols = await feed.connect()
        for missing in set(state.symbols) - set(symbols):
            state.on_feed_state(missing, "stopped", "not available on the exchange")
        if not symbols:
            raise FatalFeedError("none of the configured SYMBOLS exist on the exchange")
        if settings.telegram.send_startup_message:
            dispatcher.enqueue(format_startup(settings, symbols, feed.streaming, [c.name for c in channels]))
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
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await dispatcher.drain()
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await feed.close()
        for channel in channels:
            close = getattr(channel, "close", None)
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
