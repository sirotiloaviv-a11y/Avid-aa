"""Output formats. Terminal for humans, JSON for pipelines, SARIF for GitHub."""

from __future__ import annotations

from .html import render_html
from .json_report import render_json
from .sarif import render_sarif
from .terminal import render_terminal

__all__ = ["render_html", "render_json", "render_sarif", "render_terminal"]
