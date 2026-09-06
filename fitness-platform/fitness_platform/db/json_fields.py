"""JSON column helpers.

SQLite has no array type, so list-shaped columns are stored as JSON text. These
two functions are the only place that encoding is known, which keeps a Postgres
port (where they would become real arrays) to one file.
"""

from __future__ import annotations

import json
from typing import Any


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def loads(raw: Any, default: Any = None) -> Any:
    if default is None:
        default = []
    if raw in (None, ""):
        return default
    if isinstance(raw, (list, dict)):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default
    return parsed if parsed is not None else default
