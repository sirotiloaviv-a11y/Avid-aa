"""Credentials pasted into agent configuration.

MCP servers need API keys, and the path of least resistance is to paste the
live key into ``.mcp.json`` or ``claude_desktop_config.json``. Those files get
committed, synced and shared far more casually than a ``.env`` ever is, and a
key in ``args`` is additionally visible to every process on the machine via the
process list.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator

from ..loader import walk_strings
from ..models import (
    AGENT_DEFINITION,
    AGENT_SETTINGS,
    MCP_CONFIG,
    SKILL_DEFINITION,
    Finding,
    Severity,
    Target,
)
from . import rule

CONFIG_KINDS = (MCP_CONFIG, AGENT_SETTINGS)
ALL_KINDS = (MCP_CONFIG, AGENT_SETTINGS, AGENT_DEFINITION, SKILL_DEFINITION)

#: Provider-specific shapes. Precise patterns beat entropy for known issuers,
#: because they carry no false positives and name the vendor in the report.
PROVIDER_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("Anthropic", "sk-ant-", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI", "sk-", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("GitHub", "gh*_", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("GitHub (fine-grained)", "github_pat_", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("AWS access key", "AKIA", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Slack", "xox*-", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Google", "AIza", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe", "sk_live_", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}")),
    ("Twilio", "SK", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("SendGrid", "SG.", re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b")),
    ("Private key", "PEM", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JSON Web Token", "JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.")),
    ("Postgres URL", "postgres://", re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s]{6,}@")),
    ("MongoDB URL", "mongodb://", re.compile(r"mongodb(?:\+srv)?://[^:\s]+:[^@\s]{6,}@")),
]

#: Key names that mean "this value is a credential", for the entropy fallback.
SECRET_KEY_HINT = re.compile(
    r"(?:^|[._\-])(api[._\-]?key|secret|token|password|passwd|pwd|credential|auth|"
    r"private[._\-]?key|access[._\-]?key|client[._\-]?secret|bearer|session)",
    re.IGNORECASE,
)

#: Values that look like a credential but are a placeholder or an indirection.
PLACEHOLDER = re.compile(
    r"^\s*(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%[A-Za-z0-9_]+%|<[^>]+>|\{\{[^}]+\}\}|"
    r"your[._\-]?\w*|example|changeme|placeholder|xxx+|\.\.\.|todo|none|null|"
    r"redacted|dummy|sample|test|fake|dev)\s*$",
    re.IGNORECASE,
)


def shannon_entropy(value: str) -> float:
    """Bits per character. Random keys land above ~3.5; English words below ~3."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def redact(value: str) -> str:
    """Show enough to find the key, never enough to use it."""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 8}{value[-2:]} (len={len(value)})"


def _looks_like_secret(key: str, value: str) -> str | None:
    """Return a human reason if ``value`` is probably a live credential."""
    if not value or PLACEHOLDER.match(value) or "$" in value[:2]:
        return None
    for vendor, _, pattern in PROVIDER_PATTERNS:
        if pattern.search(value):
            return f"{vendor} credential"
    if not SECRET_KEY_HINT.search(key):
        return None
    if len(value) < 16 or " " in value or "/" in value.rstrip("/"):
        return None
    if shannon_entropy(value) < 3.4:
        return None
    return f"high-entropy value under a credential-shaped key ({shannon_entropy(value):.1f} bits/char)"


@rule("MOAT-SECRET-001", "Credential hardcoded in agent configuration", ALL_KINDS)
def hardcoded_secret(target: Target) -> Iterator[Finding]:
    strings = walk_strings(target.data) if target.data else []
    if target.body:
        strings.append(("body", target.body))

    for json_path, value in strings:
        key = json_path.rsplit(".", 1)[-1]
        reason = _looks_like_secret(key, value)
        if reason is None:
            continue
        in_args = ".args" in json_path
        yield Finding(
            rule_id="MOAT-SECRET-001",
            title=f"Hardcoded {reason} in {json_path or 'file'}",
            severity=Severity.CRITICAL,
            path=target.path,
            line=target.locate(value[:24]) or target.locate(key),
            impact=(
                "Anyone who can read this file — every collaborator, every fork, "
                "every backup and anything that syncs the directory — holds a live "
                "credential."
                + (
                    " Because it sits in `args`, it is also exposed to every local "
                    "process through the command line."
                    if in_args
                    else ""
                )
            ),
            remediation=(
                "Rotate the credential now; assume it is burned. Replace the literal "
                "with an environment reference (`\"${API_KEY}\"`) and keep the value in "
                "a secret manager or an untracked .env."
            ),
            evidence=f"{json_path}: {redact(value)}",
            meta={"json_path": json_path, "in_args": in_args},
        )


@rule("MOAT-SECRET-002", "Secret-bearing config is not ignored by git", CONFIG_KINDS)
def secret_file_tracked(target: Target) -> Iterator[Finding]:
    """A local settings file with credentials must not be committable."""
    if not target.data:
        return
    has_secret = any(
        _looks_like_secret(path.rsplit(".", 1)[-1], value)
        for path, value in walk_strings(target.data)
    )
    if not has_secret:
        return

    repo_root = _find_repo_root(target.path)
    if repo_root is None:
        return
    ignore_file = repo_root / ".gitignore"
    ignored = ignore_file.is_file() and _mentions(ignore_file, target.path.name)
    if ignored:
        return

    yield Finding(
        rule_id="MOAT-SECRET-002",
        title=f"{target.path.name} holds credentials and is not in .gitignore",
        severity=Severity.HIGH,
        path=target.path,
        line=1,
        impact=(
            "One `git add .` publishes the credential to the repository history, "
            "where deleting it later does not remove it."
        ),
        remediation=(
            f"Add `{target.path.name}` to .gitignore, and verify it is not already "
            "tracked with `git ls-files --error-unmatch`."
        ),
        evidence=f"{target.path.name} contains a credential-shaped value",
    )


def _find_repo_root(path):
    for parent in path.resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def _mentions(ignore_file, name: str) -> bool:
    try:
        text = ignore_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(name in line for line in text.splitlines() if not line.strip().startswith("#"))
