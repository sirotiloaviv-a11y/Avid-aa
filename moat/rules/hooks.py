"""Hooks: shell commands the host runs on its own.

A hook fires on a lifecycle event with no confirmation, which makes it the one
place in agent configuration where code executes without anyone deciding to run
it. Hooks also receive tool inputs — file paths, prompts, command strings — and
those values originate wherever the agent has been reading. Interpolating one
into a shell string is a command injection with an unusually short path from an
attacker's text to your shell.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..models import AGENT_SETTINGS, Finding, Severity, Target
from . import rule

KINDS = (AGENT_SETTINGS,)

#: Variables a host substitutes into a hook command, carrying model or tool data.
#: ARG must be a whole trailing segment of the name: matching it as a substring
#: turns ordinary variables like $TARGET_DIR into a command-injection finding.
INTERPOLATION = re.compile(
    r"\$\{?(CLAUDE_[A-Z_]+|TOOL_[A-Z_]+|[A-Z_]*PROMPT[A-Z_]*|[A-Z_]*INPUT[A-Z_]*"
    r"|(?:[A-Z_]*_)?ARGS?(?![A-Z]))\}?"
)
#: The same variable, but already inside single quotes (safe) or double (not).
_SINGLE_QUOTED = re.compile(r"'[^']*\$\{?(?:CLAUDE_|TOOL_)[A-Z_]+\}?[^']*'")

NETWORK_TOOLS = re.compile(r"\b(curl|wget|nc|netcat|ssh|scp|rsync|ftp|telnet|http[sx]?ie)\b")
_PIPE_TO_SHELL = re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh\b")
DESTRUCTIVE = re.compile(r"\brm\s+-[a-z]*[rf]|\bdd\s+if=|\bmkfs|\b(?:chmod|chown)\s+-R|\bgit\s+push\s+.*--force|\btruncate\b")


def _hook_commands(target: Target) -> Iterator[tuple[str, str]]:
    """Yield ``(event, command)`` for every configured hook.

    Hosts nest hooks differently (by event, by matcher, as a list or a single
    object), so we walk the block rather than assuming one shape.
    """
    block = target.data.get("hooks")
    if not isinstance(block, (dict, list)):
        return

    def walk(node, event: str) -> Iterator[tuple[str, str]]:
        if isinstance(node, dict):
            command = node.get("command")
            if isinstance(command, str) and command.strip():
                yield event, command
            for key, value in node.items():
                if key == "command":
                    continue
                yield from walk(value, event if not isinstance(node, dict) or key in ("hooks", "matcher") else key)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item, event)
        elif isinstance(node, str) and node.strip() and event:
            yield event, node

    if isinstance(block, dict):
        for event, value in block.items():
            yield from walk(value, event)
    else:
        yield from walk(block, "hook")


@rule("MOAT-HOOK-001", "Hook interpolates model-controlled data into a shell command", KINDS)
def hook_command_injection(target: Target) -> Iterator[Finding]:
    for event, command in _hook_commands(target):
        variables = INTERPOLATION.findall(command)
        if not variables:
            continue
        # Single-quoting stops word splitting and substitution; still not a
        # defence against a value containing a quote, but far weaker a signal.
        quoted = bool(_SINGLE_QUOTED.search(command))
        yield Finding(
            rule_id="MOAT-HOOK-001",
            title=f"{event} hook interpolates ${variables[0]} into a shell command",
            severity=Severity.MEDIUM if quoted else Severity.CRITICAL,
            path=target.path,
            line=target.locate(command[:40]),
            impact=(
                "The value is derived from what the model produced or read, so text "
                "in a source file, web page or issue can close the quoting and append "
                "its own command — which then runs unprompted, as you."
            ),
            remediation=(
                "Read the value from stdin or the environment inside a script "
                "(`payload=$(cat)`), never by string-substituting it into the command. "
                "Quote every expansion and validate before use."
            ),
            evidence=command.strip()[:200],
            meta={"event": event, "variables": variables, "quoted": quoted},
        )


@rule("MOAT-HOOK-002", "Hook opens a network channel", KINDS)
def hook_network_egress(target: Target) -> Iterator[Finding]:
    for event, command in _hook_commands(target):
        match = NETWORK_TOOLS.search(command)
        if not match:
            continue
        carries_data = bool(INTERPOLATION.search(command)) or bool(
            re.search(r"-d\b|--data|-F\b|-T\b|--upload-file|@-", command)
        )
        yield Finding(
            rule_id="MOAT-HOOK-002",
            title=f"{event} hook runs {match.group(1)}, sending data off the machine",
            severity=Severity.HIGH if carries_data else Severity.MEDIUM,
            path=target.path,
            line=target.locate(match.group(1)),
            impact=(
                "This fires automatically on every matching event. Combined with the "
                "agent's file access it is a ready-made exfiltration path that no "
                "prompt ever has to mention."
                if carries_data
                else "Automatic outbound traffic on every matching event, unreviewed."
            ),
            remediation=(
                "Restrict the destination to a host you control, drop the payload, or "
                "move the reporting out of the hook and into an explicit command."
            ),
            evidence=command.strip()[:200],
            meta={"event": event, "tool": match.group(1)},
        )


@rule("MOAT-HOOK-003", "Hook runs a destructive or self-updating command", KINDS)
def hook_destructive(target: Target) -> Iterator[Finding]:
    for event, command in _hook_commands(target):
        if _PIPE_TO_SHELL.search(command):
            yield Finding(
                rule_id="MOAT-HOOK-003",
                title=f"{event} hook pipes downloaded content into a shell",
                severity=Severity.CRITICAL,
                path=target.path,
                line=target.locate(command[:40]),
                impact="A remote party chooses what code runs, on every event, unattended.",
                remediation="Vendor the script, review it, and run it from a fixed path.",
                evidence=command.strip()[:200],
                meta={"event": event},
            )
            continue
        match = DESTRUCTIVE.search(command)
        if match:
            yield Finding(
                rule_id="MOAT-HOOK-003",
                title=f"{event} hook runs a destructive command (`{match.group(0).strip()}`)",
                severity=Severity.HIGH,
                path=target.path,
                line=target.locate(command[:40]),
                impact=(
                    "It runs unattended on every matching event, so a wrong path or an "
                    "unset variable destroys data with nobody watching."
                ),
                remediation="Move it into a reviewed script with explicit paths and a dry-run default.",
                evidence=command.strip()[:200],
                meta={"event": event},
            )
