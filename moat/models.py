"""Core data types: what a finding is, and what a scanned target looks like."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any


class Severity(IntEnum):
    """Higher is worse. Ordering matters for --fail-on and for report sorting."""

    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def parse(cls, name: str) -> "Severity":
        try:
            return cls[name.strip().upper()]
        except KeyError as exc:  # pragma: no cover - argparse guards this
            raise ValueError(f"unknown severity: {name!r}") from exc

    @property
    def label(self) -> str:
        return self.name.lower()


class Kind(str):
    """The flavour of a config file. Rules subscribe to these."""


#: An MCP server catalogue: .mcp.json, claude_desktop_config.json, .cursor/mcp.json
MCP_CONFIG = "mcp_config"
#: A host settings file: .claude/settings.json and friends (permissions, hooks, env)
AGENT_SETTINGS = "agent_settings"
#: A markdown-defined subagent: .claude/agents/*.md
AGENT_DEFINITION = "agent_definition"
#: A markdown-defined skill: .claude/skills/*/SKILL.md
SKILL_DEFINITION = "skill_definition"


@dataclass
class Target:
    """One configuration file, parsed once and shared by every rule.

    ``data`` is the decoded document (dict for JSON, frontmatter dict for
    markdown). ``raw`` is kept because line numbers, invisible characters and
    quoting bugs only survive in the original text.
    """

    path: Path
    kind: str
    raw: str
    data: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    #: Set when the file could not be parsed; rules that need ``data`` skip it.
    parse_error: str | None = None

    def locate(self, *needles: str) -> int:
        """First 1-based line containing every needle. Falls back to line 1.

        Config formats give us no source map, so we recover a usable line
        number by searching the raw text for the tokens that produced the
        finding. Good enough to click through to, and never wrong in a way
        that hides the issue.
        """
        wanted = [n for n in needles if n]
        if not wanted:
            return 1
        for number, line in enumerate(self.raw.splitlines(), start=1):
            if all(n in line for n in wanted):
                return number
        return 1


@dataclass
class Finding:
    """A single problem, written to be actionable without further research."""

    rule_id: str
    title: str
    severity: Severity
    path: Path
    line: int = 1
    #: What an attacker gets out of this. Never a restatement of the title.
    impact: str = ""
    #: The concrete change that closes it.
    remediation: str = ""
    #: Redacted excerpt of the offending config.
    evidence: str = ""
    #: Structured extras for the JSON/SARIF consumers.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stable id used to suppress a finding via the baseline file.

        Deliberately excludes the line number: reformatting a config should
        not resurrect findings a team already triaged.
        """
        seed = f"{self.rule_id}|{self.path.as_posix()}|{self.evidence}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


@dataclass
class Rule:
    """Metadata wrapper around a check function."""

    id: str
    name: str
    kinds: tuple[str, ...]
    check: Any

    def applies_to(self, target: Target) -> bool:
        return target.kind in self.kinds
