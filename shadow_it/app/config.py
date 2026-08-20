"""Configuration, loaded from environment variables (and an optional .env).

Everything the service needs to run is here, so a deploy is "set these vars and
start the container" — no config files to mount.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no dependency, does not overwrite real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return (os.getenv(name, "") or str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


@dataclass
class Settings:
    # --- HTTP ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    cors_origins: list[str] = field(default_factory=list)

    # --- Database --------------------------------------------------------
    database_url: str = "postgresql://shadowit:shadowit@localhost:5432/shadowit"
    db_pool_min: int = 1
    db_pool_max: int = 10
    run_migrations_on_start: bool = True

    # --- Secrets ---------------------------------------------------------
    # Fernet key (44-char urlsafe base64). Generate with:
    #   python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    # ENCRYPTION_KEYS holds retired keys so a rotation can still decrypt old
    # rows: set ENCRYPTION_KEY to the new key, keep the old one here.
    encryption_key: str = ""
    encryption_keys: list[str] = field(default_factory=list)
    # Bearer token for the admin/dashboard API. One key is enough for an MVP;
    # per-tenant keys live in the api_keys table.
    api_key: str = ""

    # --- Google Workspace OAuth (tenant onboarding) ----------------------
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Scanning --------------------------------------------------------
    # Admin SDK is rate limited per project; 8 parallel users is comfortably
    # inside the default quota and still scans ~1000 users in a few minutes.
    scan_concurrency: int = 8
    scan_max_users: int = 0  # 0 = no limit; useful for trials and smoke tests
    scan_interval_hours: int = 24

    @property
    def dsn(self) -> str:
        return self.database_url

    def validate(self) -> list[str]:
        """Return a list of fatal misconfigurations (empty means good to go)."""
        problems: list[str] = []
        if not self.encryption_key:
            problems.append("ENCRYPTION_KEY is required — refresh tokens are encrypted at rest.")
        if not self.api_key:
            problems.append("API_KEY is required — it guards every /v1 endpoint.")
        if not self.database_url:
            problems.append("DATABASE_URL is required.")
        if not (self.google_client_id and self.google_client_secret):
            problems.append(
                "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are required for the "
                "Google Workspace connector."
            )
        return problems


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or (BASE_DIR / ".env"))
    return Settings(
        host=os.getenv("HOST", "0.0.0.0"),
        port=_env_int("PORT", 8000),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        cors_origins=_env_list("CORS_ORIGINS"),
        database_url=os.getenv("DATABASE_URL", Settings.database_url),
        db_pool_min=_env_int("DB_POOL_MIN", 1),
        db_pool_max=_env_int("DB_POOL_MAX", 10),
        run_migrations_on_start=_env_bool("RUN_MIGRATIONS_ON_START", True),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        encryption_keys=_env_list("ENCRYPTION_KEYS"),
        api_key=os.getenv("API_KEY", ""),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        scan_concurrency=_env_int("SCAN_CONCURRENCY", 8),
        scan_max_users=_env_int("SCAN_MAX_USERS", 0),
        scan_interval_hours=_env_int("SCAN_INTERVAL_HOURS", 24),
    )


settings = load_settings()
