"""Input validation for everything that arrives over HTTP."""

from __future__ import annotations

import json
import re
import unicodedata

ID_RE = re.compile(r"^[0-9a-f]{32}$")
# C0/C1 controls except tab, newline, carriage return.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class ValidationError(ValueError):
    """A client error with a message safe to show the user."""


def parse_json_object(body: bytes) -> dict[str, object]:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Request body must be valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    return data


def validate_id(value: str) -> str:
    if not ID_RE.fullmatch(value):
        raise ValidationError("Invalid conversation id")
    return value


def _clean(text: str) -> str:
    return _CONTROL_RE.sub("", unicodedata.normalize("NFC", text))


def validate_title(value: object, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ValidationError("Title must be a string")
    title = " ".join(_clean(value).split())
    if not title:
        raise ValidationError("Title cannot be empty")
    if len(title) > max_chars:
        raise ValidationError(f"Title is limited to {max_chars} characters")
    return title


def validate_message(value: object, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ValidationError("Message must be a string")
    text = _clean(value).strip()
    if not text:
        raise ValidationError("Message cannot be empty")
    if len(text) > max_chars:
        raise ValidationError(f"Message is limited to {max_chars:,} characters")
    return text


def title_from_message(text: str, max_chars: int = 60) -> str:
    line = " ".join(text.split())
    return line if len(line) <= max_chars else line[: max_chars - 1].rstrip() + "…"
