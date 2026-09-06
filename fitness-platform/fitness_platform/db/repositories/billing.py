"""Subscriptions, payments and webhook bookkeeping (45)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ...domain.models import Subscription
from ...domain.subscription import SubscriptionStatus
from ..connection import execute, query, query_one, scalar


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def create_subscription(
    user_id: int,
    plan_code: str,
    amount_cents: int,
    *,
    provider: str = "mock",
    provider_ref: str = "",
    provider_customer_id: str = "",
    status: SubscriptionStatus = SubscriptionStatus.PENDING,
) -> int:
    return execute(
        """
        INSERT INTO subscriptions (user_id, plan_code, status, provider, provider_customer_id,
                                   provider_ref, amount_cents, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            plan_code,
            status.value,
            provider,
            provider_customer_id,
            provider_ref,
            amount_cents,
            _now(),
            _now(),
        ),
    )


def latest_subscription(user_id: int) -> Subscription | None:
    subscription = Subscription.from_row(
        query_one(
            "SELECT * FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        )
    )
    if subscription and subscription.status.grants_access and not subscription.is_active:
        # The paid period ran out. Reflect that in the row so the admin views and
        # every later read agree with the access decision.
        set_status(subscription.id, SubscriptionStatus.EXPIRED)
        subscription.status = SubscriptionStatus.EXPIRED
    return subscription


def get_subscription(subscription_id: int) -> Subscription | None:
    return Subscription.from_row(
        query_one("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
    )


def find_by_provider_ref(provider_ref: str) -> Subscription | None:
    return Subscription.from_row(
        query_one("SELECT * FROM subscriptions WHERE provider_ref = ? ORDER BY id DESC LIMIT 1", (provider_ref,))
    )


def set_status(subscription_id: int, status: SubscriptionStatus, *, period_days: int = 0) -> None:
    params: list[Any] = [status.value, _now()]
    period_sql = ""
    if period_days:
        end = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=period_days)
        period_sql = ", current_period_end = ?"
        params.append(end.isoformat(timespec="seconds"))
    if status is SubscriptionStatus.CANCELLED:
        period_sql += ", cancelled_at = ?"
        params.append(_now())
    params.append(subscription_id)
    execute(
        f"UPDATE subscriptions SET status = ?, updated_at = ?{period_sql} WHERE id = ?", params
    )


def set_provider_ref(subscription_id: int, provider_ref: str, customer_id: str = "") -> None:
    execute(
        "UPDATE subscriptions SET provider_ref = ?, provider_customer_id = ?, updated_at = ? WHERE id = ?",
        (provider_ref, customer_id, _now(), subscription_id),
    )


def record_payment(
    user_id: int,
    subscription_id: int | None,
    amount_cents: int,
    status: str,
    *,
    provider: str = "mock",
    provider_ref: str = "",
    currency: str = "ILS",
) -> int:
    return execute(
        """
        INSERT INTO payments (user_id, subscription_id, amount_cents, currency, status, provider, provider_ref, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, subscription_id, amount_cents, currency, status, provider, provider_ref, _now()),
    )


def webhook_seen(event_id: str) -> bool:
    return bool(scalar("SELECT COUNT(*) FROM payment_webhook_events WHERE event_id = ?", (event_id,)))


def record_webhook(event_id: str, event_type: str, payload: dict[str, Any]) -> None:
    execute(
        "INSERT OR IGNORE INTO payment_webhook_events (event_id, event_type, payload, received_at) VALUES (?, ?, ?, ?)",
        (event_id, event_type, json.dumps(payload, ensure_ascii=False), _now()),
    )


# ------------------------------------------------------------ admin views ---
def active_subscription_count() -> int:
    return int(scalar("SELECT COUNT(*) FROM subscriptions WHERE status = 'active'"))


def revenue_cents(days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    return int(
        scalar(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE status = 'succeeded' AND created_at >= ?",
            (cutoff,),
        )
    )


def recent_payments(limit: int = 8) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in query(
            """
            SELECT p.*, u.name AS user_name, u.email AS user_email, u.gender_path
              FROM payments p JOIN users u ON u.id = p.user_id
             ORDER BY p.id DESC LIMIT ?
            """,
            (limit,),
        )
    ]


def subscription_breakdown() -> dict[str, int]:
    rows = query("SELECT status, COUNT(*) AS total FROM subscriptions GROUP BY status")
    return {row["status"]: int(row["total"]) for row in rows}


def revenue_by_day(days: int = 14) -> list[dict[str, Any]]:
    rows = query(
        """
        SELECT substr(created_at, 1, 10) AS day, SUM(amount_cents) AS total
          FROM payments WHERE status = 'succeeded'
         GROUP BY day ORDER BY day DESC LIMIT ?
        """,
        (days,),
    )
    return [dict(row) for row in reversed(rows)]
