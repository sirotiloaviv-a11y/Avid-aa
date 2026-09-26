"""Position sizing, daily stop-loss, and the emergency kill switch.

Daily state (P&L and kill switch) is persisted to a JSON file so a restart
never hands the bot a fresh loss budget mid-day. Both reset at 00:00 UTC.
"""

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import config

log = logging.getLogger(__name__)


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _valid_price(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


class RiskManager:
    def __init__(
        self,
        account_balance: float = config.ACCOUNT_BALANCE,
        max_daily_loss_pct: float = config.MAX_DAILY_LOSS_PCT,
        max_risk_per_trade_pct: float = config.MAX_RISK_PER_TRADE_PCT,
        state_file: str = config.DAILY_STATE_FILE,
        executor=None,
        alert=None,
    ):
        self.account_balance = account_balance
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.state_file = Path(state_file)
        self.executor = executor    # an execution.OrderExecutor; created on demand if None
        self.alert = alert          # optional callable(str), e.g. TelegramReporter.send

        self._day = _utc_today()
        self.daily_pnl = 0.0
        self.kill_switch_active = False
        self._load_state()

    # --- persistence ------------------------------------------------------

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_file.read_text())
        except FileNotFoundError:
            self._save_state()
            return
        except (OSError, ValueError) as exc:
            # A corrupt state file must not silently grant a fresh loss budget.
            log.critical("Unreadable %s (%s): starting with kill switch ON", self.state_file, exc)
            self.kill_switch_active = True
            self._save_state()
            return

        if state.get("date") == self._day:
            self.daily_pnl = float(state.get("daily_pnl", 0.0))
            self.kill_switch_active = bool(state.get("kill_switch_active", False))
        else:
            log.info("Stored state is from %s; starting new UTC day %s", state.get("date"), self._day)
            self._save_state()

    def _save_state(self) -> None:
        state = {
            "date": self._day,
            "daily_pnl": self.daily_pnl,
            "kill_switch_active": self.kill_switch_active,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Write-then-rename so a crash mid-write can't leave a half-written file.
        tmp = self.state_file.with_name(self.state_file.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_file)

    def _roll_day(self) -> None:
        """Reset daily P&L and the kill switch once the UTC date changes.

        Called at the start of every public method, so the reset takes effect
        on the first check after 00:00 UTC.
        """
        today = _utc_today()
        if today != self._day:
            log.info(
                "UTC day rollover %s -> %s: resetting daily P&L (was %.2f) and kill switch (was %s)",
                self._day, today, self.daily_pnl, self.kill_switch_active,
            )
            self._day = today
            self.daily_pnl = 0.0
            self.kill_switch_active = False
            self._save_state()

    # --- daily loss tracking ---------------------------------------------

    @property
    def max_daily_loss(self) -> float:
        """Daily loss limit in account currency (e.g. $15,000 on $1M at 1.5%)."""
        return self.account_balance * self.max_daily_loss_pct / 100

    def record_pnl(self, pnl: float) -> None:
        """Add a realized P&L amount (negative for a loss) to today's total.

        Breaching the daily loss limit fires the emergency kill switch.
        """
        self._roll_day()
        self.daily_pnl += pnl
        self._save_state()
        if self.daily_pnl <= -self.max_daily_loss and not self.kill_switch_active:
            self.trigger_emergency_kill_switch(
                f"daily loss limit breached: {self.daily_pnl:,.2f} <= -{self.max_daily_loss:,.2f}"
            )

    def daily_limit_hit(self) -> bool:
        self._roll_day()
        return self.daily_pnl <= -self.max_daily_loss

    # --- pre-trade checks --------------------------------------------------

    def can_execute_trade(self, side: str, entry_price, stop_price) -> tuple[bool, str]:
        """Return (allowed, reason). Every trade must carry a valid stop-loss:
        a positive finite price on the losing side of the entry."""
        self._roll_day()
        if self.kill_switch_active:
            return False, "kill switch active"
        if self.daily_limit_hit():
            return False, "daily loss limit reached"
        if side not in ("buy", "sell"):
            return False, f"invalid side {side!r}"
        if not _valid_price(entry_price):
            return False, "invalid entry price"
        if stop_price is None:
            return False, "no stop-loss specified"
        if not _valid_price(stop_price):
            return False, "invalid stop-loss price"
        if side == "buy" and stop_price >= entry_price:
            return False, "stop-loss must be below entry for a buy"
        if side == "sell" and stop_price <= entry_price:
            return False, "stop-loss must be above entry for a sell"
        return True, "ok"

    def position_size(self, entry_price: float, stop_price: float) -> float:
        """Units to buy/sell so that hitting the stop loses MAX_RISK_PER_TRADE_PCT.

        Risk is also capped by what's left of today's loss budget, so a single
        trade can never push the account past the daily stop.
        """
        per_unit_risk = abs(entry_price - stop_price)
        if per_unit_risk == 0:
            raise ValueError("entry_price and stop_price must differ")
        self._roll_day()
        if self.kill_switch_active or self.daily_limit_hit():
            return 0.0

        risk_budget = self.account_balance * self.max_risk_per_trade_pct / 100
        remaining_daily = self.max_daily_loss + self.daily_pnl
        return min(risk_budget, remaining_daily) / per_unit_risk

    # --- emergency ---------------------------------------------------------

    def trigger_emergency_kill_switch(self, reason: str = "manual trigger") -> list:
        """Block all trading for the rest of the UTC day and flatten every open position.

        The kill switch is persisted *before* closing positions, so even if the
        close fails or the process dies, a restart stays locked out.
        Returns the executor's per-position close results.
        """
        self._roll_day()
        self.kill_switch_active = True
        self._save_state()
        message = f"EMERGENCY KILL SWITCH: {reason} (daily P&L {self.daily_pnl:,.2f})"
        log.critical(message)
        self._alert(message)

        if self.executor is None:
            from execution import OrderExecutor  # imported here to keep ccxt out of module import
            self.executor = OrderExecutor()
        try:
            results = self.executor.close_all_positions()
        except Exception as exc:
            log.critical("Emergency close FAILED: %s — close positions manually NOW", exc)
            self._alert(f"Emergency close FAILED: {exc} — close positions manually NOW")
            raise

        failed = [r for r in results if r.get("status") == "error"]
        summary = f"Emergency close done: {len(results) - len(failed)} closed, {len(failed)} failed"
        (log.critical if failed else log.warning)(summary)
        self._alert(summary)
        return results

    def _alert(self, text: str) -> None:
        if self.alert is None:
            return
        try:
            self.alert(text)
        except Exception as exc:  # an alert outage must never block the kill switch
            log.warning("Alert failed: %s", exc)
