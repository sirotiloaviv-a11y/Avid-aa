"""Subscription lifecycle (10, 45).

Every transition that grants or removes access happens here, and only in
response to a verified provider event.
"""

from __future__ import annotations

import logging

from ...core.errors import BadRequest, NotFound
from ...db.repositories import billing as billing_repo, insights
from ...domain.models import User
from ...domain.subscription import Plan, SubscriptionStatus, get_plan
from .. import analytics
from .factory import get_provider
from .provider import CheckoutSession, WebhookEvent

logger = logging.getLogger(__name__)


def start_checkout(user: User, plan_code: str) -> tuple[int, CheckoutSession]:
    plan = get_plan(plan_code)
    if plan is None:
        raise BadRequest("מסלול המנוי לא נמצא.")
    provider = get_provider()
    subscription_id = billing_repo.create_subscription(
        user.id, plan.code, plan.price_cents, provider=provider.name
    )
    session = provider.create_checkout(
        user_id=user.id, email=user.email, plan=plan, subscription_id=subscription_id
    )
    billing_repo.set_provider_ref(subscription_id, session.provider_ref, session.customer_id)
    analytics.track(
        analytics.SUBSCRIPTION_STARTED,
        user_id=user.id,
        gender_path=user.gender_path.value if user.gender_path else None,
        plan=plan.code,
    )
    return subscription_id, session


def handle_webhook(headers: dict[str, str], body: bytes) -> str:
    """Verify, de-duplicate and apply one provider event.

    Returns a short status string for the response body. Unknown event types are
    acknowledged and ignored so the provider stops retrying them.
    """
    provider = get_provider()
    event = provider.verify_webhook(headers, body)
    if event is None:
        raise BadRequest("חתימת webhook לא תקינה.")
    if billing_repo.webhook_seen(event.id):
        return "duplicate"
    billing_repo.record_webhook(event.id, event.type, event.raw)

    subscription = billing_repo.find_by_provider_ref(event.provider_ref)
    if subscription is None:
        logger.warning("webhook %s references unknown subscription %s", event.id, event.provider_ref)
        return "unknown_subscription"

    plan = get_plan(subscription.plan_code)
    if event.type == "payment.succeeded":
        _activate(subscription.id, subscription.user_id, plan, event)
        return "activated"
    if event.type == "payment.failed":
        billing_repo.set_status(subscription.id, SubscriptionStatus.PAST_DUE)
        billing_repo.record_payment(
            subscription.user_id, subscription.id, event.amount_cents or subscription.amount_cents,
            "failed", provider=provider.name, provider_ref=event.provider_ref,
        )
        return "past_due"
    if event.type == "subscription.cancelled":
        billing_repo.set_status(subscription.id, SubscriptionStatus.CANCELLED)
        analytics.track(analytics.SUBSCRIPTION_CANCELLED, user_id=subscription.user_id)
        return "cancelled"
    return "ignored"


def _activate(subscription_id: int, user_id: int, plan: Plan | None, event: WebhookEvent) -> None:
    period_days = plan.period_days if plan else 30
    amount = event.amount_cents or (plan.price_cents if plan else 0)
    billing_repo.set_status(subscription_id, SubscriptionStatus.ACTIVE, period_days=period_days)
    billing_repo.record_payment(
        user_id, subscription_id, amount, "succeeded",
        provider=get_provider().name, provider_ref=event.provider_ref,
    )
    analytics.track(analytics.SUBSCRIPTION_COMPLETED, user_id=user_id, plan=plan.code if plan else "")


def cancel_subscription(user: User) -> None:
    subscription = billing_repo.latest_subscription(user.id)
    if subscription is None:
        raise NotFound("לא נמצא מנוי פעיל.")
    provider = get_provider()
    provider.cancel(subscription.plan_code)
    billing_repo.set_status(subscription.id, SubscriptionStatus.CANCELLED)
    insights.record_audit(
        user.id, "subscription_cancelled", entity_type="subscription", entity_id=str(subscription.id)
    )
    analytics.track(
        analytics.SUBSCRIPTION_CANCELLED,
        user_id=user.id,
        gender_path=user.gender_path.value if user.gender_path else None,
    )
