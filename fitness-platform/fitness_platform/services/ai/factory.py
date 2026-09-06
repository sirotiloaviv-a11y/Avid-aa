"""Provider selection (44, 50)."""

from __future__ import annotations

import logging

from ...config import get_settings
from .mock_provider import MockAIProvider
from .provider import AIProvider

logger = logging.getLogger(__name__)

_cache: dict[str, AIProvider] = {}


def get_provider() -> AIProvider:
    settings = get_settings()
    name = settings.ai_provider.lower()
    cached = _cache.get(name)
    if cached is not None:
        return cached

    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        try:
            provider: AIProvider = AnthropicProvider()
        except RuntimeError as error:
            if settings.is_production:
                raise
            logger.warning("falling back to the mock AI provider: %s", error)
            provider = MockAIProvider()
    else:
        if settings.is_production and name == "mock":
            raise RuntimeError("AI_PROVIDER=mock is not allowed in production.")
        provider = MockAIProvider()

    _cache[name] = provider
    return provider


def reset_provider_cache() -> None:
    _cache.clear()
