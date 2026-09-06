"""Development payment provider (50).

It renders a clearly-labelled test checkout instead of a card form — no field on
that page ever looks like it takes a real card number. Confirming it signs a
webhook with the configured secret and posts it back through the normal handler.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from ...config import get_settings
from ...domain.subscription import Plan
from .provider import CheckoutSession, PaymentProvider, WebhookEvent

SIGNATURE_HEADER = "x-payment-signature"


def sign_payload(body: bytes) -> str:
    secret = get_settings().payment_webhook_secret.encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


class MockPaymentProvider(PaymentProvider):
    name = "mock"

    @property
    def is_mock(self) -> bool:
        return True

    def create_checkout(self, *, user_id: int, email: str, plan: Plan, subscription_id: int) -> CheckoutSession:
        reference = f"mock_{secrets.token_hex(8)}"
        return CheckoutSession(
            redirect_url=f"/billing/checkout/{subscription_id}?ref={reference}",
            provider_ref=reference,
            customer_id=f"cus_mock_{user_id}",
        )

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        signature = headers.get(SIGNATURE_HEADER, "")
        if not signature or not hmac.compare_digest(signature, sign_payload(body)):
            return None
        try:
            payload: dict[str, Any] = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        event_id = str(payload.get("id") or "")
        event_type = str(payload.get("type") or "")
        provider_ref = str(payload.get("provider_ref") or "")
        if not event_id or not event_type or not provider_ref:
            return None
        return WebhookEvent(
            id=event_id,
            type=event_type,
            provider_ref=provider_ref,
            amount_cents=int(payload.get("amount_cents") or 0),
            raw=payload,
        )

    def cancel(self, provider_ref: str) -> bool:
        return bool(provider_ref)

    # --- test-checkout helper (mock only) ---------------------------------
    def build_event(self, event_type: str, provider_ref: str, amount_cents: int) -> tuple[bytes, dict[str, str]]:
        payload = {
            "id": f"evt_{secrets.token_hex(8)}",
            "type": event_type,
            "provider_ref": provider_ref,
            "amount_cents": amount_cents,
        }
        body = json.dumps(payload).encode("utf-8")
        return body, {SIGNATURE_HEADER: sign_payload(body)}
