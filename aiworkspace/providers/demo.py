"""Demo mode: a clearly labelled, simulated provider for use without credentials.

It never pretends to be a model. Every reply starts with a notice, every stored
message is flagged ``simulated``, and the UI shows a persistent demo banner.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Iterator

from .base import ProviderError, StreamEnd, StreamEvent, TextDelta, Turn

_HEBREW = re.compile(r"[֐-׿]")

NOTICE_EN = "**Demo mode — this is a simulated reply, not live AI.**"
NOTICE_HE = "**מצב הדגמה — זו תשובה מדומה, לא בינה מלאכותית אמיתית.**"

# Typing these exact commands in demo mode exercises the UI's error state.
ERROR_TRIGGER = "/demo-error"


def _reply(prompt: str) -> str:
    chars = len(prompt)
    if _HEBREW.search(prompt):
        return (
            f"{NOTICE_HE}\n\n"
            f"קיבלתי הודעה באורך {chars} תווים. כדי לקבל תשובות אמיתיות, "
            "הגדירו `ANTHROPIC_API_KEY` בקובץ `aiworkspace/.env` והפעילו מחדש את השרת.\n\n"
            "דוגמה לבלוק קוד (נשאר משמאל לימין):\n\n"
            '```python\ndef greet(name: str) -> str:\n    return f"שלום, {name}"\n```\n'
        )
    return (
        f"{NOTICE_EN}\n\n"
        f"I received a message of {chars} characters. To get real answers, set "
        "`ANTHROPIC_API_KEY` in `aiworkspace/.env` and restart the server.\n\n"
        "Formatting preview:\n\n"
        "- **Bold**, *italic* and `inline code`\n"
        "- A fenced code block:\n\n"
        '```python\ndef greet(name: str) -> str:\n    return f"Hello, {name}"\n```\n'
    )


class DemoProvider:
    name = "demo"
    model = "demo"
    simulated = True

    def __init__(
        self, delay_s: float = 0.03, sleep: Callable[[float], None] = time.sleep
    ):
        self._delay = delay_s
        self._sleep = sleep

    def stream(
        self,
        system: str,
        turns: list[Turn],
        max_tokens: int,
        cancel: threading.Event,
        deadline: float,
    ) -> Iterator[StreamEvent]:
        last = turns[-1].content if turns else ""
        if last.strip() == ERROR_TRIGGER:
            raise ProviderError("server", "Simulated provider error (demo mode).")
        # Stream word-by-word so loading and cancellation can be exercised.
        for piece in re.findall(r"\S+\s*|\s+", _reply(last)):
            if cancel.is_set():
                yield StreamEnd("cancelled")
                return
            if time.monotonic() > deadline:
                raise ProviderError(
                    "timeout", "Simulated reply exceeded the time limit."
                )
            yield TextDelta(piece)
            self._sleep(self._delay)
        yield StreamEnd("end_turn")
