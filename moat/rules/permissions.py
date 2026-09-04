"""Standing permission grants.

A permission allowlist is a promise that the agent may take an action without
asking. Every entry is therefore a decision made in advance, on behalf of a
future situation nobody has seen yet — including the situation where the agent
is following instructions an attacker planted. These rules look for grants that
are wider than whoever wrote them intended.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..capabilities import classify_shell, Capability
from ..loader import as_list
from ..models import AGENT_DEFINITION, AGENT_SETTINGS, Finding, Severity, Target
from . import rule

KINDS = (AGENT_SETTINGS,)

#: Permission modes that switch confirmation off wholesale.
UNSAFE_MODES = {
    "bypasspermissions": "skips every confirmation prompt",
    "dontask": "stops asking before acting",
    "acceptedits": "auto-accepts file modifications",
    "yolo": "disables safety prompts",
    "auto": "acts without confirmation",
}

#: Commands whose standing approval is hard to justify, and why.
DANGEROUS_COMMANDS: dict[str, str] = {
    "curl": "fetches attacker-controlled content and can POST your data anywhere",
    "wget": "fetches attacker-controlled content",
    "nc": "opens a raw network channel",
    "netcat": "opens a raw network channel",
    "ssh": "reaches other hosts with your keys",
    "sudo": "escalates to root",
    "chmod": "can make anything executable or world-readable",
    "chown": "changes file ownership",
    "rm": "deletes files irreversibly",
    "dd": "overwrites devices",
    "mkfs": "formats filesystems",
    "eval": "executes constructed strings",
    "sh": "runs an unconstrained shell",
    "bash": "runs an unconstrained shell",
    "zsh": "runs an unconstrained shell",
    "python": "runs arbitrary code",
    "python3": "runs arbitrary code",
    "node": "runs arbitrary code",
    "perl": "runs arbitrary code",
    "ruby": "runs arbitrary code",
    "docker": "escapes the workspace and can mount the host filesystem",
    "kubectl": "acts on production clusters",
    "terraform": "changes live infrastructure",
    "aws": "acts on cloud accounts",
    "gcloud": "acts on cloud accounts",
    "git": "can push, force-push and rewrite remote history",
    "gh": "can merge, comment and change repository settings",
}

#: Subcommands that only read, so scoping to them defuses the parent command.
#: An entry may be more than one word: `gh` names a resource before the verb, so
#: it is the verb that decides whether the grant writes. `gh issue` covers
#: `gh issue create` and is therefore not read-only, while `gh issue list` is.
READ_ONLY_SUBCOMMANDS: dict[str, set[str]] = {
    "git": {"status", "diff", "log", "show", "branch", "blame", "describe", "ls-files"},
    "gh": {
        "issue list", "issue view", "issue status",
        "pr list", "pr view", "pr status", "pr diff", "pr checks",
        "repo list", "repo view",
        "run list", "run view",
    },
    "docker": {"ps", "images", "logs", "inspect"},
    "kubectl": {"get", "describe", "logs", "top"},
    "aws": set(),
}

_WILDCARD_GRANT = re.compile(r"^(?:\*|.*\(\s*[:*]*\s*\*?\s*\)?)$")


def _permission_block(target: Target) -> dict:
    block = target.data.get("permissions")
    return block if isinstance(block, dict) else {}


@rule("MOAT-PERM-001", "Confirmation prompts disabled by default", KINDS)
def unsafe_default_mode(target: Target) -> Iterator[Finding]:
    for key in ("defaultMode", "permissionMode", "mode"):
        value = _permission_block(target).get(key) or target.data.get(key)
        if not isinstance(value, str):
            continue
        reason = UNSAFE_MODES.get(value.replace("_", "").replace("-", "").lower())
        if reason is None:
            continue
        yield Finding(
            rule_id="MOAT-PERM-001",
            title=f"Default permission mode is '{value}', which {reason}",
            severity=Severity.CRITICAL if "bypass" in value.lower() else Severity.HIGH,
            path=target.path,
            line=target.locate(value),
            impact=(
                "The human review step is the last control between a poisoned "
                "instruction and a real action. With it off, a prompt injection "
                "delivered through any content the agent reads executes silently."
            ),
            remediation=(
                "Remove the mode and grant specific, scoped permissions instead. "
                "Reserve bypass modes for throwaway sandboxes with no credentials."
            ),
            evidence=f"{key}: {value}",
        )


@rule("MOAT-PERM-002", "Unbounded tool grant in the allow list", KINDS)
def wildcard_allow(target: Target) -> Iterator[Finding]:
    for entry in as_list(_permission_block(target).get("allow")):
        if not _WILDCARD_GRANT.match(entry):
            continue
        tool = entry.split("(", 1)[0] or "*"
        yield Finding(
            rule_id="MOAT-PERM-002",
            title=f"`{entry}` pre-approves every possible use of {tool}",
            severity=Severity.CRITICAL,
            path=target.path,
            line=target.locate(entry),
            impact=(
                f"Any {tool} invocation the agent can be talked into now runs "
                "without review — including ones the author never imagined."
            ),
            remediation=(
                f"Replace with the specific operations you rely on, e.g. "
                f"`{tool}(git status:*)` rather than `{entry}`."
            ),
            evidence=entry,
        )


@rule("MOAT-PERM-003", "High-risk command on the standing allow list", KINDS)
def dangerous_allow(target: Target) -> Iterator[Finding]:
    for entry in as_list(_permission_block(target).get("allow")):
        head, sep, argument = entry.partition("(")
        if not sep or head.strip().lower() not in ("bash", "shell", "terminal", "execute"):
            continue
        argument = argument.rstrip(")").replace(":*", " ")
        for segment in re.split(r"[|;&]+", argument):
            words = segment.strip().split()
            if not words:
                continue
            program = words[0].rsplit("/", 1)[-1].lower().strip("\"'*")
            reason = DANGEROUS_COMMANDS.get(program)
            if reason is None:
                continue
            # A grant scoped to a read-only subcommand is not the risk the entry
            # in DANGEROUS_COMMANDS describes: `git status` cannot push. Entries
            # are matched against both the first subcommand word and the first
            # two, so a one-word entry still defuses `git log --oneline` while
            # `gh issue` on its own remains flagged — it permits `gh issue create`.
            tokens = [word.lower().strip("*:") for word in words[1:3]]
            scoped = {" ".join(tokens[:count]) for count in range(1, len(tokens) + 1)}
            if scoped & READ_ONLY_SUBCOMMANDS.get(program, set()):
                continue
            capability = classify_shell(argument)
            severity = Severity.HIGH if Capability.EXFIL in capability else Severity.MEDIUM
            yield Finding(
                rule_id="MOAT-PERM-003",
                title=f"`{entry}` runs {program} without asking — it {reason}",
                severity=severity,
                path=target.path,
                line=target.locate(entry),
                impact=(
                    f"The agent may run {program} at any time, on any argument the "
                    "grant pattern matches, with no human in the loop."
                ),
                remediation=(
                    f"Narrow the pattern to the exact invocation you need, or move "
                    f"{program} to `permissions.ask` so it still works but pauses."
                ),
                evidence=entry,
                meta={"program": program, "capabilities": capability.names},
            )
            break


@rule("MOAT-PERM-004", "Filesystem access reaches outside the project", KINDS)
def broad_directories(target: Target) -> Iterator[Finding]:
    entries = as_list(_permission_block(target).get("additionalDirectories")) or as_list(
        target.data.get("additionalDirectories")
    )
    risky = {
        "/": "the entire filesystem",
        "~": "the whole home directory, including SSH keys and browser profiles",
        "$HOME": "the whole home directory",
        "/etc": "system configuration",
        "/var": "system and service data",
        "..": "the parent of the project",
    }
    for entry in entries:
        normalized = entry.rstrip("/") or "/"
        reason = risky.get(normalized) or risky.get(entry.strip())
        if reason is None and normalized.startswith(".."):
            reason = "a directory above the project root"
        if reason is None:
            continue
        yield Finding(
            rule_id="MOAT-PERM-004",
            title=f"Agent is granted access to {reason} (`{entry}`)",
            severity=Severity.HIGH,
            path=target.path,
            line=target.locate(entry),
            impact=(
                "File-reading tools can now reach SSH keys, cloud credential files "
                "and other projects' secrets, none of which this agent needs."
            ),
            remediation="Grant only the specific directories the task requires.",
            evidence=f"additionalDirectories: {entry}",
        )


@rule("MOAT-PERM-005", "Web access allowed to any domain", KINDS)
def open_web_access(target: Target) -> Iterator[Finding]:
    for entry in as_list(_permission_block(target).get("allow")):
        head, sep, argument = entry.partition("(")
        if head.strip().lower() not in ("webfetch", "fetch", "websearch"):
            continue
        argument = argument.rstrip(")").strip()
        if sep and argument and not _WILDCARD_GRANT.match(entry) and "*" not in argument.split(":")[-1]:
            continue
        yield Finding(
            rule_id="MOAT-PERM-005",
            title=f"`{entry}` lets the agent fetch any URL without asking",
            severity=Severity.HIGH,
            path=target.path,
            line=target.locate(entry),
            impact=(
                "An unrestricted fetch is a two-way channel: it pulls in text that "
                "can carry instructions, and it can carry your data out inside the "
                "URL it requests."
            ),
            remediation=(
                "Pin the grant to the hosts you actually use, e.g. "
                "`WebFetch(domain:docs.example.com)`."
            ),
            evidence=entry,
        )


@rule("MOAT-PERM-006", "Subagent inherits every tool", (AGENT_DEFINITION,))
def agent_inherits_all_tools(target: Target) -> Iterator[Finding]:
    """A subagent with no ``tools`` key inherits the full parent tool set."""
    declared = target.data.get("tools", target.data.get("allowed-tools"))
    name = str(target.data.get("name") or target.path.stem)
    values = as_list(declared)

    if declared is None:
        yield Finding(
            rule_id="MOAT-PERM-006",
            title=f"Subagent '{name}' declares no tool list and inherits all of them",
            severity=Severity.MEDIUM,
            path=target.path,
            line=1,
            impact=(
                "The subagent runs with the parent's full authority, so a narrow "
                "helper carries the same blast radius as the main agent."
            ),
            remediation=(
                "Add a `tools:` line naming only what this agent needs — most "
                "review and research agents need nothing beyond Read, Grep and Glob."
            ),
            evidence="frontmatter has no `tools` key",
        )
        return

    if any(value.strip() in ("*", "all") for value in values):
        yield Finding(
            rule_id="MOAT-PERM-006",
            title=f"Subagent '{name}' is granted every tool via a wildcard",
            severity=Severity.HIGH,
            path=target.path,
            line=target.locate("tools"),
            impact="The wildcard also grants any tool added to the host in future.",
            remediation="Replace the wildcard with an explicit tool list.",
            evidence=f"tools: {declared}",
        )
