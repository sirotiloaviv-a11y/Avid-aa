"""Position sizing and daily stop-loss enforcement."""

from datetime import date

import config


class RiskManager:
    def __init__(
        self,
        account_balance: float = config.ACCOUNT_BALANCE,
        max_daily_loss_pct: float = config.MAX_DAILY_LOSS_PCT,
        max_risk_per_trade_pct: float = config.MAX_RISK_PER_TRADE_PCT,
    ):
        self.account_balance = account_balance
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.daily_pnl = 0.0
        self._day = date.today()

    @property
    def max_daily_loss(self) -> float:
        """Daily loss limit in account currency (e.g. $15,000 on $1M at 1.5%)."""
        return self.account_balance * self.max_daily_loss_pct / 100

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self.daily_pnl = 0.0

    def record_pnl(self, pnl: float) -> None:
        """Add a realized P&L amount (negative for a loss) to today's total."""
        self._roll_day()
        self.daily_pnl += pnl

    def daily_limit_hit(self) -> bool:
        self._roll_day()
        return self.daily_pnl <= -self.max_daily_loss

    def can_trade(self) -> bool:
        return not self.daily_limit_hit()

    def position_size(self, entry_price: float, stop_price: float) -> float:
        """Units to buy/sell so that hitting the stop loses MAX_RISK_PER_TRADE_PCT.

        Risk is also capped by what's left of today's loss budget, so a single
        trade can never push the account past the daily stop.
        """
        per_unit_risk = abs(entry_price - stop_price)
        if per_unit_risk == 0:
            raise ValueError("entry_price and stop_price must differ")
        if not self.can_trade():
            return 0.0

        risk_budget = self.account_balance * self.max_risk_per_trade_pct / 100
        remaining_daily = self.max_daily_loss + self.daily_pnl
        return min(risk_budget, remaining_daily) / per_unit_risk
