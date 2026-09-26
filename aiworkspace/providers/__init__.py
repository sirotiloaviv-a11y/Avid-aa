"""Model adapters. Add new text providers here; see aiworkspace/README.md."""

from __future__ import annotations

from ..config import Settings
from .anthropic import AnthropicProvider
from .base import ProviderError, StreamEnd, TextDelta, TextProvider, Turn
from .demo import DemoProvider

__all__ = [
    "AnthropicProvider",
    "DemoProvider",
    "ProviderError",
    "StreamEnd",
    "TextDelta",
    "TextProvider",
    "Turn",
    "build_provider",
]


def build_provider(settings: Settings) -> TextProvider:
    if settings.resolved_provider == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            fallbacks=settings.anthropic_fallbacks,
        )
    return DemoProvider()
