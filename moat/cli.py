"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import Severity
from .reporters import render_json, render_sarif, render_terminal
from .rules import load_all, load_project_rules
from .scanner import scan
from .version import __version__

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moat",
        description=(
            "Audit what your AI agents are actually allowed to do. "
            "Scans MCP server definitions, permission allowlists, hooks, subagents "
            "and skills for credential leaks, unreviewed code execution, prompt "
            "injection surface and data-exfiltration paths."
        ),
        epilog="Exit code 1 means findings at or above --fail-on. 0 means clean.",
    )
    parser.add_argument("path", nargs="?", default=".", help="file or directory to scan (default: .)")
    parser.add_argument(
        "--format", choices=("text", "json", "sarif"), default="text", help="output format"
    )
    parser.add_argument("-o", "--output", metavar="FILE", help="write the report to a file")
    parser.add_argument(
        "--fail-on",
        default="high",
        metavar="LEVEL",
        help="exit non-zero at this severity or worse: critical, high, medium, low, info, never",
    )
    parser.add_argument(
        "--min-severity", default="info", metavar="LEVEL", help="hide findings below this severity"
    )
    parser.add_argument("--baseline", metavar="FILE", help="suppress fingerprints listed in this file")
    parser.add_argument(
        "--write-baseline",
        metavar="FILE",
        help="record every current finding as accepted, so only new ones fail later",
    )
    parser.add_argument(
        "--disable", action="append", default=[], metavar="RULE", help="rule id to skip (repeatable)"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip paths matching this glob, e.g. 'examples/*' (repeatable)",
    )
    parser.add_argument("--list-rules", action="store_true", help="print the rule catalogue and exit")
    parser.add_argument("--version", action="version", version=f"moat {__version__}")
    return parser


def _severity(value: str, parser: argparse.ArgumentParser) -> Severity | None:
    if value.strip().lower() in ("never", "none", "off"):
        return None
    try:
        return Severity.parse(value)
    except ValueError:
        parser.error(f"unknown severity {value!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_rules:
        for rule in sorted(load_all() + load_project_rules(), key=lambda r: r.id):
            scope = "project" if rule.kinds == ("*",) else ", ".join(rule.kinds)
            print(f"{rule.id:22} {rule.name}\n{'':22} applies to: {scope}\n")
        return EXIT_OK

    root = Path(args.path)
    if not root.exists():
        parser.error(f"no such path: {root}")

    fail_on = _severity(args.fail_on, parser)
    min_severity = _severity(args.min_severity, parser) or Severity.INFO

    result = scan(
        root,
        baseline=Path(args.baseline) if args.baseline else None,
        min_severity=min_severity,
        disabled=set(args.disable),
        exclude=tuple(args.exclude),
    )

    if args.write_baseline:
        payload = {
            "version": 1,
            "note": "Fingerprints accepted for this repository. Remove an entry to re-report it.",
            "fingerprints": sorted(f.fingerprint for f in result.findings),
        }
        Path(args.write_baseline).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(result.findings)} fingerprint(s) to {args.write_baseline}", file=sys.stderr)
        return EXIT_OK

    if args.format == "json":
        report = render_json(result, root)
    elif args.format == "sarif":
        report = render_sarif(result, root)
    else:
        report = render_terminal(result, root, stream=sys.stdout)

    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    else:
        print(report)

    if fail_on is not None and result.worst is not None and result.worst >= fail_on:
        return EXIT_FINDINGS
    return EXIT_OK


def run() -> int:
    """Entry point that survives being piped into `head`."""
    try:
        return main()
    except BrokenPipeError:  # pragma: no cover - depends on the consumer
        try:
            sys.stdout.close()
        finally:
            return EXIT_OK
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
