"""Human-readable report.

A security report is only useful if the reader can act on it without a second
tool, so each finding shows what it is, why it matters and the exact change to
make. Colour is emitted only when the stream is a TTY.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ..models import Severity
from ..scanner import ScanResult

_COLOURS = {
    Severity.CRITICAL: "\033[97;41m",
    Severity.HIGH: "\033[91m",
    Severity.MEDIUM: "\033[93m",
    Severity.LOW: "\033[94m",
    Severity.INFO: "\033[90m",
}
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _supports_colour(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _wrap(text: str, width: int, indent: str) -> str:
    import textwrap

    return "\n".join(
        textwrap.fill(paragraph, width=width, initial_indent=indent, subsequent_indent=indent)
        for paragraph in text.split("\n")
        if paragraph.strip()
    )


def render_terminal(result: ScanResult, root: Path, stream=None) -> str:
    stream = stream or sys.stdout
    colour = _supports_colour(stream)
    width = min(shutil.get_terminal_size((100, 24)).columns, 100)

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if colour else text

    lines: list[str] = []
    lines.append(paint("moat", _BOLD) + f"  ·  scanned {len(result.targets)} agent config file(s) under {root}")
    lines.append("")

    if not result.findings:
        lines.append(paint("  No findings.", "\033[92m"))
        if result.suppressed:
            lines.append(paint(f"  ({result.suppressed} suppressed by baseline)", _DIM))
        lines.append("")
        return "\n".join(lines)

    for finding in result.findings:
        badge = paint(f" {finding.severity.label.upper():^8} ", _COLOURS[finding.severity])
        try:
            location = finding.path.resolve().relative_to(Path(root).resolve())
        except ValueError:
            location = finding.path
        lines.append(f"{badge} {paint(finding.title, _BOLD)}")
        lines.append(paint(f"          {location}:{finding.line}  [{finding.rule_id}]", _DIM))
        if finding.impact:
            lines.append(_wrap(finding.impact, width, "          "))
        if finding.evidence:
            lines.append(paint(_wrap(f"evidence: {finding.evidence}", width, "          "), _DIM))
        if finding.remediation:
            lines.append(_wrap(f"fix: {finding.remediation}", width, "          "))
        lines.append("")

    tally = result.counts()
    summary = "  ".join(
        paint(f"{count} {label}", _COLOURS[Severity.parse(label)])
        for label, count in tally.items()
        if count
    )
    lines.append(paint("─" * width, _DIM))
    lines.append(f"  {summary}")
    if result.suppressed:
        lines.append(paint(f"  {result.suppressed} suppressed by baseline", _DIM))
    if result.errors:
        lines.append(paint(f"  {len(result.errors)} file(s) could not be analysed fully", _DIM))
    lines.append("")
    return "\n".join(lines)
