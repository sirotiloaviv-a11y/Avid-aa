"""Central configuration.

Every value that differs between a laptop, a staging box and production lives
here and comes from the environment. Nothing in this module reads a secret at
import time in a way that would let it reach the browser: templates receive the
``PublicConfig`` view, which deliberately carries no keys.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Mode = Literal["mock", "development", "production"]

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime settings for one process."""

    # --- Branding (41) -----------------------------------------------------
    brand_name: str = field(default_factory=lambda: _env("BRAND_NAME", "FitLife"))
    brand_tagline: str = field(
        default_factory=lambda: _env("BRAND_TAGLINE", "כושר שנבנה בשבילך")
    )
    support_email: str = field(
        default_factory=lambda: _env("SUPPORT_EMAIL", "hello@example.com")
    )

    # --- Environment -------------------------------------------------------
    env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    debug: bool = field(default_factory=lambda: _flag("APP_DEBUG", True))
    host: str = field(default_factory=lambda: _env("APP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("APP_PORT", 8000))
    base_url: str = field(default_factory=lambda: _env("APP_BASE_URL", ""))

    # --- Database ----------------------------------------------------------
    database_path: str = field(
        default_factory=lambda: _env("DATABASE_PATH", str(PROJECT_DIR / "var" / "app.db"))
    )

    # --- Security ----------------------------------------------------------
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY"))
    session_ttl_seconds: int = field(
        default_factory=lambda: _int("SESSION_TTL_SECONDS", 60 * 60 * 24 * 14)
    )
    secure_cookies: bool = field(default_factory=lambda: _flag("SECURE_COOKIES", False))
    password_iterations: int = field(
        default_factory=lambda: _int("PASSWORD_ITERATIONS", 240_000)
    )
    rate_limit_per_minute: int = field(
        default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 240)
    )
    auth_rate_limit_per_minute: int = field(
        default_factory=lambda: _int("AUTH_RATE_LIMIT_PER_MINUTE", 12)
    )

    # --- Pluggable providers (50) -----------------------------------------
    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "mock"))
    ai_api_key: str = field(default_factory=lambda: _env("AI_API_KEY"))
    ai_model: str = field(default_factory=lambda: _env("AI_MODEL", "claude-sonnet-5"))
    ai_daily_message_limit: int = field(
        default_factory=lambda: _int("AI_DAILY_MESSAGE_LIMIT", 60)
    )

    payment_provider: str = field(default_factory=lambda: _env("PAYMENT_PROVIDER", "mock"))
    payment_api_key: str = field(default_factory=lambda: _env("PAYMENT_API_KEY"))
    payment_webhook_secret: str = field(
        default_factory=lambda: _env("PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret")
    )

    storage_provider: str = field(default_factory=lambda: _env("STORAGE_PROVIDER", "local"))
    storage_root: str = field(
        default_factory=lambda: _env("STORAGE_ROOT", str(PROJECT_DIR / "var" / "uploads"))
    )
    storage_public_prefix: str = field(
        default_factory=lambda: _env("STORAGE_PUBLIC_PREFIX", "/uploads")
    )

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        if not self.secret_key:
            if self.is_production:
                raise RuntimeError(
                    "SECRET_KEY must be set in production. Refusing to start with an "
                    "ephemeral key: every session would be invalidated on restart."
                )
            object.__setattr__(self, "secret_key", secrets.token_urlsafe(48))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def mode(self) -> Mode:
        """Which integration mode the process runs in (50)."""
        if self.is_production:
            return "production"
        if self.ai_provider == "mock" and self.payment_provider == "mock":
            return "mock"
        return "development"

    def public(self) -> "PublicConfig":
        """The subset that is safe to render into HTML."""
        return PublicConfig(
            brand_name=self.brand_name,
            brand_tagline=self.brand_tagline,
            support_email=self.support_email,
            mode=self.mode,
            debug=self.debug,
        )


@dataclass(frozen=True)
class PublicConfig:
    brand_name: str
    brand_tagline: str
    support_email: str
    mode: Mode
    debug: bool


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Used by tests that patch the environment."""
    global _settings
    _settings = None
