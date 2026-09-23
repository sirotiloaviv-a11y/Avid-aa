"""Alert formatting and delivery to Telegram.

Formatting is pure (``format_alert`` turns a TradePlan into Telegram HTML) so
it can be tested and previewed without a bot. Delivery goes through an
:class:`AlertDispatcher` queue: market tasks enqueue and move on, and a single
worker sends with retries, so a slow or rate-limited Telegram never stalls the
market data loops.

``python-telegram-bot`` is imported lazily, only when a real bot is created.
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from .config import Settings
from .risk_manager import TradePlan
from .strategy import Direction

log = logging.getLogger(__name__)

# Telegram rejects messages above 4096 characters.
MAX_MESSAGE_LENGTH = 4096

# Errors that will fail the same way on every retry.
_PERMANENT_ERRORS = {"BadRequest", "Forbidden", "InvalidToken", "Conflict"}


# ---------------------------------------------------------------- formatting


def format_price(price: float) -> str:
    """Enough decimals to be tradable at any price scale (BTC, SOL, PEPE ...)."""
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:,.4f}"
    if price <= 0:
        return f"{price:g}"
    return f"{price:.8f}".rstrip("0").rstrip(".") if price >= 1e-4 else f"{price:.10f}".rstrip("0")


def format_units(units: float) -> str:
    if units >= 1000:
        return f"{units:,.2f}"
    return f"{units:,.8f}".rstrip("0").rstrip(".")


def format_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def format_pct(pct: float) -> str:
    return f"{pct:+.2f}%".replace("-", "−")


def _base_asset(symbol: str) -> str:
    return symbol.split("/")[0]


def _utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_alert(plan: TradePlan, timeframe_ms: Optional[int] = None) -> str:
    """Render a trade plan as a Telegram HTML message."""
    sig = plan.signal
    e = html.escape
    is_long = sig.direction is Direction.LONG
    header = "🟢 <b>LONG</b>" if is_long else "🔴 <b>SHORT</b>"
    zone_low, zone_high = plan.entry_zone
    chase_note = (
        f"don't chase above {format_price(zone_high)}" if is_long
        else f"don't chase below {format_price(zone_low)}"
    )
    base = e(_base_asset(sig.symbol))

    lines = [
        f"{header} · <b>{e(sig.symbol)}</b> · {e(sig.timeframe)}",
        f"⚡ <i>{e(sig.summary or sig.strategy)}</i>",
        "",
        f"🎯 <b>Entry:</b> <code>{format_price(zone_low)} – {format_price(zone_high)}</code>",
        f"      <i>{e(chase_note)}</i>",
        f"🛑 <b>Stop Loss:</b> <code>{format_price(plan.stop_loss)}</code> ({format_pct(plan.stop_loss_pct)})",
        f"      <i>{e(plan.stop_method)}</i>",
        f"✅ <b>Take Profit:</b> <code>{format_price(plan.take_profit)}</code> ({format_pct(plan.take_profit_pct)})",
        f"⚖️ <b>Risk/Reward:</b> 1 : {plan.risk_reward_ratio:g}",
        "",
        "💰 <b>Position Size</b>",
        f"• Size: <code>{format_usd(plan.notional)}</code> ({plan.leverage:.2f}x equity)",
        f"• Units: <code>{format_units(plan.units)} {base}</code>",
        f"• Loss at SL: <code>{format_usd(plan.risk_amount)}</code> ({plan.risk_pct_of_equity:.2f}% of equity)",
        f"• Profit at TP: <code>{format_usd(plan.reward_amount)}</code>",
    ]
    if plan.capped_by_leverage:
        lines.append(
            f"⚠️ <i>Size capped by MAX_LEVERAGE — risking less than the {format_usd(plan.risk_budget)} budget</i>"
        )

    lines += ["", "📊 <b>Trigger Reasons</b>"]
    lines += [f"• {e(reason)}" for reason in sig.reasons]

    atr_text = format_price(sig.atr) if sig.atr >= 1 else f"{sig.atr:.4g}"
    context = [f"RSI {sig.rsi:.1f}", f"ATR {atr_text}"]
    if sig.fast_ma is not None:
        context.append(f"EMA fast {format_price(sig.fast_ma)}")
    if sig.slow_ma is not None:
        trend = "above" if sig.entry_price > sig.slow_ma else "below"
        context.append(f"price {trend} EMA slow {format_price(sig.slow_ma)}")
    lines += ["", f"<i>{e(' · '.join(context))}</i>"]

    close_ts = sig.candle.timestamp + (timeframe_ms or 0)
    label = "Candle closed" if timeframe_ms else "Candle opened"
    lines.append(f"<i>🕒 {label} {_utc(close_ts)} · {e(sig.strategy)}</i>")
    return "\n".join(lines)[:MAX_MESSAGE_LENGTH]


def format_startup(settings: Settings, symbols: list[str], streaming: bool) -> str:
    ex, risk = settings.exchange, settings.risk
    return "\n".join(
        [
            "🤖 <b>Crypto alert system online</b>",
            f"Exchange: <code>{html.escape(ex.exchange_id)}</code> ({'websocket' if streaming else 'REST polling'})",
            f"Timeframe: <code>{html.escape(ex.timeframe)}</code>",
            f"Watching: {html.escape(', '.join(symbols)) or '—'}",
            f"Risk/trade: {format_usd(risk.risk_budget)} ({risk.risk_per_trade_pct:g}% of {format_usd(risk.account_equity)})",
            f"Target R:R: 1 : {risk.risk_reward_ratio:g} · Stops: {html.escape(risk.stop_mode)}",
        ]
    )


# ----------------------------------------------------------------- delivery


class Notifier(Protocol):
    async def send(self, text: str) -> bool: ...


class ConsoleNotifier:
    """Prints alerts instead of sending them (DRY_RUN=true)."""

    async def send(self, text: str) -> bool:
        print(f"\n{'=' * 60}\n{text}\n{'=' * 60}", flush=True)
        return True


class TelegramNotifier:
    """Sends HTML messages to one chat, retrying transient failures."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        max_attempts: int = 5,
        bot: Any | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.max_attempts = max_attempts
        self._token = token
        self._bot = bot

    @property
    def bot(self) -> Any:
        if self._bot is None:
            try:
                from telegram import Bot
            except ImportError as exc:
                raise RuntimeError(
                    "python-telegram-bot is not installed: pip install -r crypto_alerts/requirements.txt"
                ) from exc
            self._bot = Bot(token=self._token)
        return self._bot

    async def send(self, text: str) -> bool:
        """Send ``text``; returns False if it could not be delivered after retrying."""
        delay = 1.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                names = {cls.__name__ for cls in type(exc).__mro__}
                if names & _PERMANENT_ERRORS:
                    log.error("Telegram rejected the message (%s: %s) — not retrying", type(exc).__name__, exc)
                    return False
                if attempt == self.max_attempts:
                    log.error("Telegram send failed after %d attempts: %r", attempt, exc)
                    return False
                # RetryAfter (flood control) says how long to wait: int or timedelta.
                retry_after = getattr(exc, "retry_after", None)
                if hasattr(retry_after, "total_seconds"):
                    retry_after = retry_after.total_seconds()
                wait = float(retry_after) if retry_after else delay
                log.warning("Telegram send failed (%r); retry %d in %.1fs", exc, attempt, wait)
                await asyncio.sleep(wait)
                delay = min(delay * 2, 30.0)
        return False

    async def close(self) -> None:
        if self._bot is not None and hasattr(self._bot, "shutdown"):
            try:
                await self._bot.shutdown()
            except Exception as exc:
                log.debug("bot.shutdown() failed: %s", exc)


class AlertDispatcher:
    """Queue in front of a notifier so senders never block on the network."""

    def __init__(self, notifier: Notifier, maxsize: int = 200) -> None:
        self.notifier = notifier
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self.sent = 0
        self.failed = 0

    def enqueue(self, text: str) -> None:
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            log.error("Alert queue full — dropping alert: %s", text.splitlines()[0] if text else "")

    async def run(self) -> None:
        """Worker loop: deliver queued messages until cancelled."""
        while True:
            text = await self._queue.get()
            try:
                ok = await self.notifier.send(text)
                if ok:
                    self.sent += 1
                else:
                    self.failed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failed += 1
                log.exception("Notifier raised while sending an alert")
            finally:
                self._queue.task_done()

    async def drain(self, timeout: float = 10.0) -> None:
        """Wait (bounded) for queued alerts to go out, e.g. before shutdown."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout)
        except asyncio.TimeoutError:
            log.warning("Shutdown with %d alert(s) still queued", self._queue.qsize())


def create_notifier(settings: Settings) -> Notifier:
    if settings.telegram.dry_run:
        return ConsoleNotifier()
    return TelegramNotifier(settings.telegram.bot_token, settings.telegram.chat_id)
