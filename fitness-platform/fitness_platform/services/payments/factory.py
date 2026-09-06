"""Payment provider selection (45, 50)."""

from __future__ import annotations

from ...config import get_settings
from .mock_provider import MockPaymentProvider
from .provider import PaymentProvider

_cache: dict[str, PaymentProvider] = {}


def get_provider() -> PaymentProvider:
    settings = get_settings()
    name = settings.payment_provider.lower()
    cached = _cache.get(name)
    if cached is not None:
        return cached
    if name != "mock":
        raise RuntimeError(
            f"PAYMENT_PROVIDER={name} has no implementation yet. Implement PaymentProvider "
            "for the gateway and register it here; the rest of the app needs no change."
        )
    if settings.is_production:
        raise RuntimeError("PAYMENT_PROVIDER=mock is not allowed in production.")
    provider = MockPaymentProvider()
    _cache[name] = provider
    return provider


def reset_provider_cache() -> None:
    _cache.clear()
