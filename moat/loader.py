"""Parsing helpers.

Agent config files are hand-edited, so they routinely contain things
``json.loads`` rejects: ``//`` comments, block comments and trailing commas.
Refusing to parse those would mean silently skipping exactly the files most
likely to be sloppy elsewhere, so we normalise first and parse after.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments that sit outside of string literals."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    quote = ""
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                in_string = False
            i += 1
            continue
        if ch in "\"'":
            in_string, quote = True, ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_json(text: str) -> tuple[dict[str, Any], str | None]:
    """Parse tolerantly. Returns ``(data, error)``; data is {} on failure."""
    for candidate in (text, _TRAILING_COMMA.sub(r"\1", strip_jsonc(text))):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed, None
        return {}, "top-level value is not an object"
    return {}, "invalid JSON"


_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def load_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``---`` YAML frontmatter from a markdown body.

    Agent and skill files use a flat, one-level frontmatter (name, description,
    tools, model, allowed-tools). Pulling in a YAML dependency to read five
    scalar keys is not worth the install friction, so we parse that shape
    directly and treat anything nested as opaque.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    data: dict[str, Any] = {}
    list_key: str | None = None
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and list_key:
            data.setdefault(list_key, [])
            if isinstance(data[list_key], list):
                data[list_key].append(_scalar(stripped[2:]))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            list_key = key
            data[key] = []
            continue
        list_key = None
        data[key] = _scalar(value)
    return data, text[match.end():]


def _scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(v) for v in value[1:-1].split(",") if v.strip()]
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return value


def as_list(value: Any) -> list[str]:
    """Coerce the several shapes a tool list shows up in into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def walk_strings(node: Any, path: str = "") -> list[tuple[str, str]]:
    """Yield every ``(json_path, string)`` in a decoded document.

    Several rules (secrets, invisible characters, injection phrasing) care
    about any string anywhere rather than about one known key, and config
    schemas vary between hosts. Walking is more robust than enumerating keys.
    """
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(walk_strings(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            found.extend(walk_strings(value, f"{path}[{index}]"))
    elif isinstance(node, str):
        found.append((path, node))
    return found
