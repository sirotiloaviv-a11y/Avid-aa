"""Settings, read from the process environment and an optional aiworkspace/.env.

Real environment variables win over the .env file. The API key is held only in
this object on the server; it is never serialised to the browser or logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = PACKAGE_DIR / ".env"
DEFAULT_DB_PATH = PACKAGE_DIR / ".data" / "workspace.sqlite3"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Supports comments and single/double quotes."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _int(env: dict[str, str], key: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not lo <= value <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = DEFAULT_DB_PATH

    # "auto" picks anthropic when a key is present, otherwise demo.
    provider: str = "auto"
    anthropic_api_key: str = field(default="", repr=False)
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-opus-5"
    # Server-side refusal fallbacks (beta, opt-in). "off" or "default".
    anthropic_fallbacks: str = "off"
    # Automatic retries per message, only for requests the API rejected
    # before generating (429/5xx/529) or that never connected.
    max_retries: int = 2

    max_message_chars: int = 16_000
    max_output_tokens: int = 16_000
    max_context_chars: int = 200_000
    request_timeout_s: int = 120
    rate_limit_per_minute: int = 20
    max_title_chars: int = 120

    @property
    def resolved_provider(self) -> str:
        if self.provider == "auto":
            return "anthropic" if self.anthropic_api_key else "demo"
        return self.provider


def load_settings(
    environ: dict[str, str] | None = None, env_file: Path | None = DEFAULT_ENV_FILE
) -> Settings:
    env: dict[str, str] = {}
    if env_file is not None:
        env.update(parse_env_file(env_file))
    env.update(os.environ if environ is None else environ)

    host = env.get("AIWS_HOST", "127.0.0.1").strip()
    if host not in LOOPBACK_HOSTS:
        # Phase 1 has no authentication. Binding elsewhere would expose every
        # conversation and the API key's spending power to the network.
        raise ValueError(
            "AIWS_HOST must be a loopback address (127.0.0.1, localhost or ::1). "
            "Public or multi-user deployment needs authentication first."
        )

    provider = env.get("AIWS_PROVIDER", "auto").strip().lower() or "auto"
    if provider not in {"auto", "anthropic", "demo"}:
        raise ValueError("AIWS_PROVIDER must be auto, anthropic or demo")

    fallbacks = env.get("AIWS_ANTHROPIC_FALLBACKS", "off").strip().lower() or "off"
    if fallbacks not in {"default", "off"}:
        raise ValueError("AIWS_ANTHROPIC_FALLBACKS must be default or off")

    key = env.get("ANTHROPIC_API_KEY", "").strip()
    if provider == "anthropic" and not key:
        raise ValueError("AIWS_PROVIDER=anthropic requires ANTHROPIC_API_KEY")

    db_raw = env.get("AIWS_DB_PATH", "").strip()
    return Settings(
        host=host,
        port=_int(env, "AIWS_PORT", 8765, 1, 65535),
        db_path=Path(db_raw).expanduser() if db_raw else DEFAULT_DB_PATH,
        provider=provider,
        anthropic_api_key=key,
        anthropic_base_url=(
            env.get("ANTHROPIC_BASE_URL", "").strip() or "https://api.anthropic.com"
        ).rstrip("/"),
        anthropic_model=env.get("AIWS_MODEL", "").strip() or "claude-opus-5",
        anthropic_fallbacks=fallbacks,
        max_retries=_int(env, "AIWS_MAX_RETRIES", 2, 0, 3),
        max_message_chars=_int(env, "AIWS_MAX_MESSAGE_CHARS", 16_000, 1, 200_000),
        max_output_tokens=_int(env, "AIWS_MAX_OUTPUT_TOKENS", 16_000, 1, 128_000),
        max_context_chars=_int(
            env, "AIWS_MAX_CONTEXT_CHARS", 200_000, 1_000, 2_000_000
        ),
        request_timeout_s=_int(env, "AIWS_REQUEST_TIMEOUT_S", 120, 5, 900),
        rate_limit_per_minute=_int(env, "AIWS_RATE_LIMIT_PER_MINUTE", 20, 1, 600),
    )
