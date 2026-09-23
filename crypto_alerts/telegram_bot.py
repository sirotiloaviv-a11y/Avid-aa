"""Alert formatting and the Telegram channel.

Formatting is pure (``format_alert`` turns a TradePlan into Telegram HTML) so
it can be tested and previewed without a bot. Delivery happens in
:class:`TelegramNotifier`, one of the channels the dispatcher in
``notifiers.py`` fans alerts out to.

``python-telegram-bot`` is imported lazily, only when a real bot is created.
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from .config import Settings
from .notifiers import Notification
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


def _liquidity_lines(plan: TradePlan) -> list[str]:
    """The 💧 section: expected slippage and what the guard did about it."""
    e = html.escape
    liq = plan.liquidity
    if plan.liquidity_error:
        return [f"💧 ⚠️ <i>Order book unavailable ({e(plan.liquidity_error)}) — slippage unknown</i>"]
    if liq is None:
        return []
    base = e(_base_asset(plan.symbol))
    detail = f"spread {liq.spread_pct:.3f}% · limit {liq.threshold_pct:g}%"
    if plan.liquidity_action == "ok":
        return [f"💧 <b>Liquidity:</b> ✅ ~{liq.slippage_pct:.3f}% slippage for full size <i>({detail})</i>"]
    lines = []
    if plan.liquidity_action == "reduced" and plan.original_units is not None:
        lines.append(
            f"💧 <b>Liquidity:</b> 📉 size reduced from {format_units(plan.original_units)} {base} "
            f"to fit {liq.threshold_pct:g}% slippage — ~{liq.slippage_pct:.3f}% now <i>({detail})</i>"
        )
        return lines
    if not liq.fully_filled:
        lines.append(
            f"💧 ⚠️ <b>THIN BOOK:</b> visible depth fills only {format_units(liq.filled_units)} of "
            f"{format_units(liq.units)} {base} <i>({detail})</i>"
        )
    else:
        lines.append(
            f"💧 ⚠️ <b>THIN BOOK:</b> expected slippage {liq.slippage_pct:.3f}% &gt; {liq.threshold_pct:g}% "
            f"<i>({detail})</i>"
        )
    lines.append(
        f"      <i>max size within limit ≈ {format_units(liq.max_units_within_threshold)} {base} "
        f"({format_usd(liq.max_units_within_threshold * plan.entry)}) — use limit orders or scale in</i>"
    )
    if plan.risk_with_slippage is not None:
        lines.append(f"      <i>loss at SL incl. slippage ≈ {format_usd(plan.risk_with_slippage)}</i>")
    return lines


def format_alert(plan: TradePlan, timeframe_ms: Optional[int] = None, urgent: bool = False) -> str:
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

    lines = []
    if urgent:
        lines.append("🚨🔥 <b>HIGH CONVICTION</b> 🔥🚨")
    lines += [
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
    liquidity = _liquidity_lines(plan)
    if liquidity:
        lines += [""] + liquidity

    lines += ["", "📊 <b>Trigger Reasons</b>"]
    lines += [f"• {e(reason)}" for reason in sig.reasons]
    if sig.conviction_factors:
        lines += ["", "🔥 <b>Conviction</b>"]
        lines += [f"• {e(factor)}" for factor in sig.conviction_factors]

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


def format_push(plan: TradePlan) -> str:
    """Compact alert for push channels (Pushover allows 1024 chars and a small HTML subset)."""
    sig = plan.signal
    e = html.escape
    zone_low, zone_high = plan.entry_zone
    lines = [
        f"<b>Entry</b> {format_price(zone_low)} – {format_price(zone_high)}",
        f"<b>SL</b> {format_price(plan.stop_loss)} ({format_pct(plan.stop_loss_pct)}) · "
        f"<b>TP</b> {format_price(plan.take_profit)} ({format_pct(plan.take_profit_pct)})",
        f"<b>Size</b> {format_usd(plan.notional)} = {format_units(plan.units)} {e(_base_asset(sig.symbol))}",
        f"<b>Risk</b> {format_usd(plan.risk_amount)} · R:R 1:{plan.risk_reward_ratio:g}",
        e(sig.summary),
    ]
    if sig.conviction_factors:
        lines.append("🔥 " + e(", ".join(sig.conviction_factors)))
    if plan.liquidity_action == "warned":
        lines.append("⚠️ Thin order book — expect slippage")
    elif plan.liquidity_action == "reduced":
        lines.append("📉 Size reduced for liquidity")
    return "\n".join(lines)


def alert_title(plan: TradePlan, urgent: bool) -> str:
    direction = "🟢 LONG" if plan.direction is Direction.LONG else "🔴 SHORT"
    return f"{'🚨 ' if urgent else ''}{direction} {plan.symbol} {plan.signal.timeframe}"


def format_startup(settings: Settings, symbols: list[str], streaming: bool, channels: list[str]) -> str:
    ex, risk, liq = settings.exchange, settings.risk, settings.liquidity
    liquidity = (
        f"on — max slippage {liq.max_slippage_pct:g}%, action: {html.escape(liq.action)}" if liq.enabled else "off"
    )
    return "\n".join(
        [
            "🤖 <b>Crypto alert system online</b>",
            f"Exchange: <code>{html.escape(ex.exchange_id)}</code> ({'websocket' if streaming else 'REST polling'})",
            f"Timeframe: <code>{html.escape(ex.timeframe)}</code>",
            f"Watching: {html.escape(', '.join(symbols)) or '—'}",
            f"Risk/trade: {format_usd(risk.risk_budget)} ({risk.risk_per_trade_pct:g}% of {format_usd(risk.account_equity)})",
            f"Target R:R: 1 : {risk.risk_reward_ratio:g} · Stops: {html.escape(risk.stop_mode)}",
            f"Liquidity guard: {liquidity}",
            f"Channels: {html.escape(', '.join(channels))}",
        ]
    )


def format_risk_change(old_equity: float, old_pct: float, new_equity: float, new_pct: float, source: str) -> str:
    return "\n".join(
        [
            f"⚙️ <b>Risk settings changed</b> <i>({html.escape(source)})</i>",
            f"Equity: {format_usd(old_equity)} → <b>{format_usd(new_equity)}</b>",
            f"Risk/trade: {old_pct:g}% → <b>{new_pct:g}%</b> "
            f"(= {format_usd(new_equity * new_pct / 100)} per trade)",
        ]
    )


# ------------------------------------------------------------------ delivery


class TelegramNotifier:
    """Sends HTML messages to the main chat, and urgent ones to an optional urgent chat."""

    name = "telegram"

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        urgent_chat_id: str = "",
        quiet_normal_alerts: bool = False,
        max_attempts: int = 5,
        bot: Any | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.urgent_chat_id = urgent_chat_id
        self.quiet_normal_alerts = quiet_normal_alerts
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

    def accepts(self, notification: Notification) -> bool:
        return True

    async def send(self, notification: Notification) -> bool:
        """Deliver to the main chat (and the urgent chat for urgent alerts)."""
        silent = self.quiet_normal_alerts and not notification.urgent and notification.kind == "alert"
        targets = [self.send_text(self.chat_id, notification.text, silent=silent)]
        if notification.urgent and self.urgent_chat_id and self.urgent_chat_id != self.chat_id:
            targets.append(self.send_text(self.urgent_chat_id, notification.text))
        results = await asyncio.gather(*targets)
        return all(results)

    async def send_text(self, chat_id: str, text: str, *, silent: bool = False) -> bool:
        """Send ``text``; returns False if it could not be delivered after retrying."""
        delay = 1.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    disable_notification=silent,
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
