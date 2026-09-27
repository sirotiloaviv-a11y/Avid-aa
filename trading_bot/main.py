"""Main trading loop: market data → strategy → risk engine → brokers.

Run with ``python -m trading_bot.main`` (same as ``python -m trading_bot run``).

Threads:
  * feeds: one per WebSocket / simulator, each pushing closed candles into a queue
  * loop (the main thread): consumes candles, runs the strategy, executes
    signals, reconciles accounts every ``ACCOUNT_POLL_SECONDS``, applies
    queued flatten requests (halts), and flattens ahead of news if configured
  * dashboard, Telegram, control poller: started by :class:`BotRuntime`

SIGINT / SIGTERM stop the loop cleanly: feeds are closed, in-flight orders
finish, state is already in SQLite. Open positions are **not** closed on
shutdown; their stops and targets rest at the broker.
"""

from __future__ import annotations

import argparse
import queue
import signal
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Callable, Sequence

from .brokers.base import Broker
from .brokers.bybit import BybitBroker, BybitKlineFeed
from .brokers.marketdata import CompositeFeed, MarketDataFeed, ReplayFeed, SimulatedFeed
from .brokers.paper import PaperBroker
from .brokers.tradovate import TradovateBroker, TradovateChartFeed, TradovateCredentials, default_device_id
from .config import (
    BrokerKind,
    ConfigError,
    Environment,
    MarketDataSource,
    Settings,
    load_settings,
)
from .risk_manager.events import ExitReason
from .risk_manager.news_guard import NewsGuard
from .risk_manager.position_sizing import INSTRUMENTS, AssetClass
from .risk_manager.risk_engine import RiskManager
from .strategies.base import Strategy
from .strategies.ema_cross import EmaCrossStrategy
from .strategies.executor import AccountRoute, ExecutionEngine
from .strategies.models import Candle
from .utils.logger import get_logger, setup_logging
from .utils.state_store import StateStore

log = get_logger(__name__)


class TradingLoop:
    def __init__(
        self,
        *,
        strategy: Strategy,
        executor: ExecutionEngine,
        feed: MarketDataFeed,
        paper: PaperBroker | None = None,
        news_guard: NewsGuard | None = None,
        flatten_on_news: bool = True,
        poll_seconds: float = 5.0,
    ) -> None:
        self.strategy = strategy
        self.executor = executor
        self.feed = feed
        self.paper = paper
        self.news_guard = news_guard
        self.flatten_on_news = flatten_on_news
        self.poll_seconds = poll_seconds
        self._candles: queue.Queue[Candle] = queue.Queue(maxsize=10_000)
        self._last_poll = 0.0
        self._news_flattened_for: object | None = None
        self.candles_seen = 0

    def _enqueue(self, candle: Candle) -> None:
        try:
            self._candles.put_nowait(candle)
        except queue.Full:
            log.error("Candle queue full; dropping %s %s", candle.symbol, candle.start)

    def start(self) -> None:
        self.executor.reconcile()  # fresh balances before the first signal
        self._last_poll = time.monotonic()
        self.feed.start(self._enqueue)
        log.info("Trading loop started: %s on %s (%s bars)", self.strategy.name,
                 ", ".join(self.strategy.symbols), self.strategy.timeframe)

    def stop(self) -> None:
        self.feed.stop()
        self.executor.close()
        log.info("Trading loop stopped after %d candles", self.candles_seen)

    def handle_candle(self, candle: Candle) -> None:
        self.candles_seen += 1
        if self.paper is not None:
            self.paper.on_candle(candle)  # simulated stops/targets first
        signal = self.strategy.process_candle(candle)
        if signal is not None:
            self.executor.on_signal(signal)

    def step(self, timeout: float = 1.0) -> None:
        """One loop iteration. Never raises: the loop must survive bad data."""
        try:
            try:
                candle = self._candles.get(timeout=timeout)
            except queue.Empty:
                candle = None
            while candle is not None:
                self.handle_candle(candle)
                try:
                    candle = self._candles.get_nowait()
                except queue.Empty:
                    candle = None
            self.executor.process_requests()
            self._flatten_before_news()
            if time.monotonic() - self._last_poll >= self.poll_seconds:
                self._last_poll = time.monotonic()
                self.executor.reconcile()
        except Exception:
            log.exception("Trading loop iteration failed")

    def _flatten_before_news(self) -> None:
        if not self.flatten_on_news or self.news_guard is None or not self.news_guard.enabled:
            return
        check = self.news_guard.check(refresh=False)
        if check.event is None:  # no blackout (a missing calendar only blocks entries)
            return
        if self._news_flattened_for == check.event:
            return
        if self.executor.open_position_count():
            log.warning("Flattening all accounts ahead of %s", check.event.title)
            self.executor.flatten_all(ExitReason.NEWS_HALT)
        self._news_flattened_for = check.event


# ------------------------------------------------------------------ builders
def build_strategy(settings: Settings) -> Strategy:
    cfg = settings.trading.strategy
    return EmaCrossStrategy(
        cfg.symbols, timedelta(minutes=cfg.timeframe_minutes), fast=cfg.ema_fast, slow=cfg.ema_slow,
        atr_period=cfg.atr_period, atr_stop_mult=cfg.atr_stop_mult, reward_risk=cfg.reward_risk,
        allow_short=cfg.allow_short,
    )


def build_brokers(settings: Settings, store: StateStore) -> tuple[dict[str, Broker], list[AccountRoute]]:
    trading = settings.trading
    live = settings.environment is Environment.LIVE
    brokers: dict[str, Broker] = {}
    routes: list[AccountRoute] = []
    initial = {a.account_id: a.initial_balance for a in settings.accounts}
    paper_accounts = {r.broker_account: initial[r.account_id] for r in trading.routes
                      if r.broker is BrokerKind.PAPER}
    if paper_accounts:
        brokers["paper"] = PaperBroker(paper_accounts, store=store)
    if any(r.broker is BrokerKind.TRADOVATE for r in trading.routes):
        t = trading.tradovate
        brokers["tradovate"] = TradovateBroker(
            TradovateCredentials(t.username, t.password, t.app_id, t.app_version, t.cid, t.secret,
                                 default_device_id()),
            dict(t.contracts), live=live,
        )
    if any(r.broker is BrokerKind.BYBIT for r in trading.routes):
        brokers["bybit"] = BybitBroker({a: (k, s) for a, k, s in trading.bybit_keys}, testnet=not live)
    for route in trading.routes:
        if route.broker is BrokerKind.PAPER:
            classes = frozenset({AssetClass(route.asset_class)}) if route.asset_class \
                else frozenset(AssetClass)
        else:
            broker_class = brokers[route.broker.value].asset_class
            classes = frozenset({broker_class}) if broker_class else frozenset(AssetClass)
        routes.append(AccountRoute(route.account_id, route.broker.value, route.broker_account, classes))
    return brokers, routes


def build_feed(settings: Settings, brokers: dict[str, Broker]) -> MarketDataFeed:
    trading = settings.trading
    symbols = list(trading.strategy.symbols)
    timeframe = timedelta(minutes=trading.strategy.timeframe_minutes)
    live = settings.environment is Environment.LIVE
    if trading.market_data is MarketDataSource.REPLAY:
        assert trading.replay_file is not None
        return ReplayFeed.from_csv(Path(trading.replay_file), timeframe, delay=trading.simulated_bar_seconds or 0.0)
    if trading.market_data is MarketDataSource.SIMULATED:
        return SimulatedFeed(symbols, timeframe, interval=trading.simulated_bar_seconds)

    crypto = [s for s in symbols if INSTRUMENTS[s].asset_class is AssetClass.CRYPTO]
    futures = [s for s in symbols if INSTRUMENTS[s].asset_class is AssetClass.FUTURES]
    feeds: list[MarketDataFeed] = []
    if crypto:
        # Public data, no key needed. Testnet prices when orders go to testnet.
        feeds.append(BybitKlineFeed(crypto, timeframe, testnet="bybit" in brokers and not live))
    if futures:
        tradovate = brokers.get("tradovate")
        if isinstance(tradovate, TradovateBroker):
            feeds.append(TradovateChartFeed(tradovate.auth, tradovate.contracts, futures, timeframe))
        elif live:
            raise ConfigError(f"no live market data for {futures}: route an account to tradovate")
        else:
            log.warning("No futures data source; SIMULATED bars for %s (paper only)", futures)
            feeds.append(SimulatedFeed(futures, timeframe, interval=trading.simulated_bar_seconds))
    return feeds[0] if len(feeds) == 1 else CompositeFeed(feeds)


def build_trading_loop(
    settings: Settings,
    manager: RiskManager,
    store: StateStore,
    news_guard: NewsGuard | None,
    *,
    alert: Callable[[str], None] | None = None,
) -> TradingLoop:
    brokers, routes = build_brokers(settings, store)
    for name, broker in brokers.items():
        try:
            broker.connect()
        except Exception as exc:  # keep going: stale data blocks entries until it recovers
            log.error("Broker %s failed to connect: %s", name, exc)
            if alert is not None:
                alert(f"⚠️ Broker <b>{name}</b> failed to connect: {exc}")
    replay = settings.trading.market_data is MarketDataSource.REPLAY
    timeframe = timedelta(minutes=settings.trading.strategy.timeframe_minutes)
    executor = ExecutionEngine(manager, routes, brokers, alert=alert,
                               max_signal_age=None if replay else timeframe * 2)
    manager.on_halt(executor.on_halt)
    paper = brokers.get("paper")
    return TradingLoop(
        strategy=build_strategy(settings), executor=executor, feed=build_feed(settings, brokers),
        paper=paper if isinstance(paper, PaperBroker) else None, news_guard=news_guard,
        flatten_on_news=settings.trading.flatten_on_news,
        poll_seconds=settings.trading.account_poll_seconds,
    )


# ---------------------------------------------------------------------- run
def run(settings: Settings) -> int:
    from .runtime import AlreadyRunning, BotRuntime

    try:
        runtime = BotRuntime(settings)
    except AlreadyRunning as exc:
        print(f"Bot already running: {exc}", file=sys.stderr)
        return 1
    stop = threading.Event()

    def _on_signal(signum: int, _frame: object) -> None:
        log.warning("Received signal %d; shutting down", signum)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)
    runtime.start()
    if runtime.dashboard is not None:
        print(f"Dashboard: http://{settings.dashboard.host}:{runtime.dashboard.port}")
    print("Trading: " + ("ENABLED" if runtime.trading is not None else "off (monitoring only)"))
    try:
        runtime.run_until(stop)
    finally:
        runtime.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m trading_bot.main")
    parser.add_argument("--env-file", default=None, help="path to .env")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(Path(args.env_file)) if args.env_file else load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    setup_logging(settings.log_dir, settings.log_level)
    return run(settings)


if __name__ == "__main__":
    sys.exit(main())
