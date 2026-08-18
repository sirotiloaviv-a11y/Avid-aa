"""Configuration, loaded from environment variables (and an optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .keywords import DEFAULT_RULES, KeywordMatcher

BASE_DIR = Path(__file__).resolve().parent


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


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return (os.getenv(name, "") or str(default)).strip().lower() in {"1", "true", "yes", "on"}


# Israeli news feeds that publish security items quickly. Override with RSS_FEEDS.
DEFAULT_FEEDS: tuple[str, ...] = (
    "https://www.ynet.co.il/Integration/StoryRss1854.xml",   # ynet — ביטחון
    "https://www.ynet.co.il/Integration/StoryRss2.xml",      # ynet — חדשות
    "https://rcs.mako.co.il/rss/news-military.xml",          # mako — צבא וביטחון
    "https://www.israelhayom.co.il/rss.xml",                 # ישראל היום
    "https://www.maariv.co.il/Rss/RssFeedsMivzakiZahav",     # מעריב — מבזקים
)


@dataclass
class Config:
    # --- Telegram -------------------------------------------------------
    bot_token: str = ""
    alert_chat_id: str = ""
    # Channels the bot is an ADMIN of. The Bot API cannot read channels you
    # do not control — see README for the RSS-bridge workaround.
    telegram_channels: list[str] = field(default_factory=list)

    # --- Sources --------------------------------------------------------
    rss_feeds: list[str] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    rss_poll_seconds: int = 60
    telegram_poll_seconds: int = 25
    http_timeout_seconds: int = 20
    max_items_per_feed: int = 25

    # --- Behaviour ------------------------------------------------------
    matcher: KeywordMatcher = field(default_factory=lambda: KeywordMatcher(DEFAULT_RULES))
    state_path: Path = BASE_DIR / "state" / "seen.json"
    state_max_entries: int = 5000
    # Suppress repeats of the same phrase from the same source for N seconds.
    cooldown_seconds: int = 0
    prime_without_alerting: bool = True
    log_level: str = "INFO"

    # --- Cameras (see cameras.py) --------------------------------------
    cameras_enabled: bool = False
    camera_snapshot_on_severity: str = "CRITICAL"

    # --- AI assistant (see assistant.py) --------------------------------
    anthropic_api_key: str = ""
    assistant_enabled: bool = False
    assistant_model: str = "claude-opus-5"
    assistant_effort: str = "medium"
    assistant_name: str = "קארן"
    assistant_owner_name: str = "אביב"
    assistant_history_turns: int = 12
    # Add a line of context to alerts at or above this severity.
    assistant_brief_on_severity: str = "CRITICAL"

    # --- Voice (see voice.py) -------------------------------------------
    voice_enabled: bool = False
    voice_provider: str = "openai"          # openai | local | none
    openai_api_key: str = ""
    voice_transcribe_model: str = "whisper-1"
    voice_speak_model: str = "gpt-4o-mini-tts"
    voice_name: str = "shimmer"
    voice_whisper_model: str = "small"      # local provider only
    # match = answer in the medium the question arrived in.
    voice_reply_mode: str = "match"         # match | voice | text | both

    # --- Dashboard (see dashboard.py) -----------------------------------
    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080
    dashboard_token: str = ""
    alert_history_size: int = 100

    @classmethod
    def from_env(cls, dotenv: Path | None = None) -> "Config":
        _load_dotenv(dotenv or BASE_DIR.parent / ".env")
        _load_dotenv(BASE_DIR / ".env")

        keywords_spec = os.getenv("KEYWORDS", "").strip()
        matcher = (
            KeywordMatcher.from_spec(keywords_spec)
            if keywords_spec
            else KeywordMatcher(DEFAULT_RULES)
        )

        feeds = _env_list("RSS_FEEDS") or list(DEFAULT_FEEDS)

        return cls(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            alert_chat_id=os.getenv("TELEGRAM_ALERT_CHAT_ID", "").strip(),
            telegram_channels=_env_list("TELEGRAM_CHANNELS"),
            rss_feeds=feeds,
            rss_poll_seconds=_env_int("RSS_POLL_SECONDS", 60),
            telegram_poll_seconds=_env_int("TELEGRAM_POLL_SECONDS", 25),
            http_timeout_seconds=_env_int("HTTP_TIMEOUT_SECONDS", 20),
            max_items_per_feed=_env_int("MAX_ITEMS_PER_FEED", 25),
            matcher=matcher,
            state_path=Path(os.getenv("STATE_PATH", str(BASE_DIR / "state" / "seen.json"))),
            state_max_entries=_env_int("STATE_MAX_ENTRIES", 5000),
            cooldown_seconds=_env_int("ALERT_COOLDOWN_SECONDS", 0),
            prime_without_alerting=_env_bool("PRIME_WITHOUT_ALERTING", True),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            cameras_enabled=_env_bool("CAMERAS_ENABLED", False),
            camera_snapshot_on_severity=os.getenv("CAMERA_SNAPSHOT_ON_SEVERITY", "CRITICAL").upper(),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            assistant_enabled=_env_bool("ASSISTANT_ENABLED", False),
            assistant_model=os.getenv("ASSISTANT_MODEL", "claude-opus-5").strip(),
            assistant_effort=os.getenv("ASSISTANT_EFFORT", "medium").strip().lower(),
            assistant_name=os.getenv("ASSISTANT_NAME", "קארן").strip(),
            assistant_owner_name=os.getenv("ASSISTANT_OWNER_NAME", "אביב").strip(),
            assistant_history_turns=_env_int("ASSISTANT_HISTORY_TURNS", 12),
            assistant_brief_on_severity=os.getenv(
                "ASSISTANT_BRIEF_ON_SEVERITY", "CRITICAL"
            ).upper(),
            voice_enabled=_env_bool("VOICE_ENABLED", False),
            voice_provider=os.getenv("VOICE_PROVIDER", "openai").strip().lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            voice_transcribe_model=os.getenv("VOICE_TRANSCRIBE_MODEL", "whisper-1").strip(),
            voice_speak_model=os.getenv("VOICE_SPEAK_MODEL", "gpt-4o-mini-tts").strip(),
            voice_name=os.getenv("VOICE_NAME", "shimmer").strip(),
            voice_whisper_model=os.getenv("VOICE_WHISPER_MODEL", "small").strip(),
            voice_reply_mode=os.getenv("VOICE_REPLY_MODE", "match").strip().lower(),
            dashboard_enabled=_env_bool("DASHBOARD_ENABLED", True),
            dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1").strip(),
            dashboard_port=_env_int("DASHBOARD_PORT", 8080),
            dashboard_token=os.getenv("DASHBOARD_TOKEN", "").strip(),
            alert_history_size=_env_int("ALERT_HISTORY_SIZE", 100),
        )

    @property
    def alert_history_path(self) -> Path:
        """Alert history lives beside the dedupe state."""
        return self.state_path.parent / "alerts.json"

    def validate(self) -> list[str]:
        """Return a list of fatal configuration problems (empty means OK)."""
        problems: list[str] = []
        if not self.bot_token:
            problems.append("TELEGRAM_BOT_TOKEN is not set.")
        if not self.alert_chat_id:
            problems.append("TELEGRAM_ALERT_CHAT_ID is not set.")
        if not self.rss_feeds and not self.telegram_channels:
            problems.append("No sources configured (RSS_FEEDS and TELEGRAM_CHANNELS are both empty).")
        if self.rss_poll_seconds < 15:
            problems.append("RSS_POLL_SECONDS below 15 is abusive to news sites; raise it.")
        if self.assistant_enabled and not self.anthropic_api_key:
            problems.append(
                "ASSISTANT_ENABLED is on but ANTHROPIC_API_KEY is not set."
            )
        if self.assistant_enabled and self.assistant_effort not in {
            "low", "medium", "high", "xhigh", "max",
        }:
            problems.append(
                f"ASSISTANT_EFFORT is '{self.assistant_effort}' — must be one of "
                "low, medium, high, xhigh, max."
            )
        if self.voice_enabled and not self.assistant_enabled:
            problems.append(
                "VOICE_ENABLED is on but ASSISTANT_ENABLED is off — there is "
                "nothing to talk to. Turn on the assistant as well."
            )
        if self.voice_enabled and self.voice_provider == "openai" and not self.openai_api_key:
            problems.append("VOICE_PROVIDER is openai but OPENAI_API_KEY is not set.")
        if self.voice_enabled and self.voice_provider not in {"openai", "local", "none"}:
            problems.append(
                f"VOICE_PROVIDER is '{self.voice_provider}' — must be openai, local or none."
            )
        if self.voice_reply_mode not in {"match", "voice", "text", "both"}:
            problems.append(
                f"VOICE_REPLY_MODE is '{self.voice_reply_mode}' — must be "
                "match, voice, text or both."
            )
        if (
            self.dashboard_enabled
            and self.dashboard_host not in {"127.0.0.1", "localhost", "::1"}
            and not self.dashboard_token
        ):
            problems.append(
                f"DASHBOARD_HOST is {self.dashboard_host} but DASHBOARD_TOKEN is empty — "
                "that publishes your alert history to anyone who can reach the port. "
                "Set a token, or bind to 127.0.0.1."
            )
        return problems
