"""Subscription plans and lifecycle (10, 45)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SubscriptionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def grants_access(self) -> bool:
        """Only these states open the product area.

        ``cancelled`` still grants access until the paid period ends; the
        repository clears it to ``expired`` once ``current_period_end`` passes,
        so the check here stays a pure function of status.
        """
        return self in {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED}

    @property
    def label(self) -> str:
        return {
            SubscriptionStatus.PENDING: "ממתין לתשלום",
            SubscriptionStatus.ACTIVE: "פעיל",
            SubscriptionStatus.PAST_DUE: "תשלום נכשל",
            SubscriptionStatus.CANCELLED: "בוטל",
            SubscriptionStatus.EXPIRED: "הסתיים",
        }[self]

    @classmethod
    def parse(cls, raw: object) -> "SubscriptionStatus":
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.PENDING


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_cents: int
    interval: str          # "month" | "year"
    period_days: int
    highlights: tuple[str, ...]
    badge: str = ""

    @property
    def price_display(self) -> str:
        return f"{self.price_cents // 100:,}".replace(",", ",")

    @property
    def monthly_equivalent_cents(self) -> int:
        return self.price_cents if self.interval == "month" else round(self.price_cents / 12)


PLANS: tuple[Plan, ...] = (
    Plan(
        code="monthly",
        name="מנוי חודשי",
        price_cents=14900,
        interval="month",
        period_days=30,
        highlights=(
            "תוכנית אימונים אישית",
            "תפריט שבועי מותאם",
            "ספריית סרטונים מלאה",
            "רשימת קניות אוטומטית",
            "ביטול בכל עת",
        ),
    ),
    Plan(
        code="yearly",
        name="מנוי שנתי",
        price_cents=119000,
        interval="year",
        period_days=365,
        badge="החיסכון הכי גדול",
        highlights=(
            "כל מה שבמנוי החודשי",
            "חיסכון של כ‑33% בשנה",
            "ליווי AI Coach מורחב",
            "גישה לתוכניות עונתיות",
            "עדכוני תוכן ראשונים",
        ),
    ),
)

PLANS_BY_CODE = {plan.code: plan for plan in PLANS}


def get_plan(code: str) -> Plan | None:
    return PLANS_BY_CODE.get((code or "").strip().lower())
