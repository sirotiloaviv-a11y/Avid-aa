"""The payment provider seam (45).

The rule this file exists to enforce: the browser never decides that a member
paid. A checkout hands off to the provider, and access is granted only when a
signed webhook says the money moved. The mock provider follows the same path —
it signs and posts a real webhook — so development and production exercise the
same activation code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ...domain.subscription import Plan


@dataclass
class CheckoutSession:
    redirect_url: str
    provider_ref: str
    customer_id: str = ""


@dataclass
class WebhookEvent:
    id: str
    type: str                       # payment.succeeded | payment.failed | subscription.cancelled
    provider_ref: str
    amount_cents: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(ABC):
    name = "abstract"

    @abstractmethod
    def create_checkout(self, *, user_id: int, email: str, plan: Plan, subscription_id: int) -> CheckoutSession:
        ...

    @abstractmethod
    def verify_webhook(self, headers: dict[str, str], body: bytes) -> WebhookEvent | None:
        """Return the event only if the signature checks out, else ``None``."""

    @abstractmethod
    def cancel(self, provider_ref: str) -> bool:
        ...

    @property
    def is_mock(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "mock": self.is_mock, "ready": True}


class PaymentError(RuntimeError):
    pass
