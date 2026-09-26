"""Send status updates to a Telegram chat via the Bot API."""

import logging

import requests

import config

log = logging.getLogger(__name__)


class TelegramReporter:
    def __init__(self, token: str = config.TELEGRAM_BOT_TOKEN, chat_id: str = config.TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return not (self.token.startswith("YOUR_") or self.chat_id.startswith("YOUR_"))

    def send(self, text: str) -> bool:
        """Send a message. Returns False (and logs) instead of raising on failure,
        so a Telegram outage never interrupts trading."""
        if not self.enabled:
            log.info("[telegram disabled] %s", text)
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Telegram send failed: %s", exc)
            return False
