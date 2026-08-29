"""The combination that actually leaks data.

Individually, every grant in an agent's config can be defended. The exposure
appears when three of them coexist for the same principal:

1. it can reach **private data** (your files, your repos, your database),
2. it can ingest **untrusted input** (a web page, an issue, an email — text
   somebody else wrote), and
3. it can **send data outward** (an HTTP request, a message, a commit).

At that point no software bug is required. The attacker writes instructions
into content the agent was always going to read, and the agent — behaving
exactly as designed — reads a secret and sends it somewhere. Splitting the
capabilities so that no single principal holds all three is the mitigation,
which is why this analysis reasons about principals instead of lines.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..capabilities import (
    ALL_THREE,
    WRITE_VERBS,
    Capability,
    capabilities_of,
    split_mcp,
    witnesses,
)
from ..loader import as_list
from ..models import (
    AGENT_DEFINITION,
    AGENT_SETTINGS,
    MCP_CONFIG,
    Finding,
    Severity,
    Target,
)
from . import project_rule

_LABELS = {
    "private_data": "read private data",
    "untrusted_input": "ingest attacker-controlled text",
    "exfil": "send data outward",
}


def project_root(target: Target) -> Path:
    """The scope a set of config files share.

    Settings under ``.claude/`` and an ``.mcp.json`` beside it configure one
    agent, so they must be evaluated together.
    """
    resolved = target.path.resolve()
    for parent in resolved.parents:
        if parent.name in (".claude", ".cursor", ".vscode"):
            return parent.parent
    return resolved.parent


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Deny entries use shell-style globs; translate one to a matcher."""
    escaped = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile(f"^{escaped}$", re.IGNORECASE)


class DenyList:
    """What ``permissions.deny`` actually takes away.

    Deny is only allowed to reduce a capability when it demonstrably covers it.
    A partial deny — three write tools blocked out of a server's twenty — leaves
    the capability intact, and saying otherwise would turn a half-finished
    mitigation into a green report.
    """

    def __init__(self, entries: list[str], disabled_servers: list[str] | None = None):
        self.entries = [e.strip() for e in entries if e.strip()]
        self.patterns = [_glob_to_regex(e.split("(", 1)[0].strip()) for e in self.entries]
        self.disabled = {s.strip().lower() for s in (disabled_servers or [])}

    def blocks(self, tool: str) -> bool:
        """True when the grant is removed outright."""
        bare = tool.split("(", 1)[0].strip()
        server, sub = split_mcp(bare)
        if server in self.disabled or bare.lower() in self.disabled:
            return True
        if any(pattern.match(bare) for pattern in self.patterns):
            return True
        # Denying a server denies every tool it exposes.
        if sub and any(pattern.match(f"mcp__{server}") for pattern in self.patterns):
            return True
        return False

    def reduce(self, tool: str, capability: Capability) -> Capability:
        """Subtract capability that the deny list provably removes."""
        server, sub = split_mcp(tool.split("(", 1)[0].strip())
        if sub:
            return capability
        # A wholesale server grant loses its outbound half only if every write
        # verb it could expose is denied.
        prefix = f"mcp__{server}__"
        if Capability.EXFIL in capability and all(
            any(pattern.match(f"{prefix}{verb}_x") for pattern in self.patterns) for verb in WRITE_VERBS
        ):
            capability &= ~Capability.EXFIL
        return capability


def _deny_list(target: Target) -> DenyList:
    block = target.data.get("permissions")
    entries = as_list(block.get("deny")) if isinstance(block, dict) else []
    disabled = as_list(target.data.get("disabledMcpjsonServers"))
    return DenyList(entries, disabled)


def _server_names(target: Target) -> tuple[list[str], dict[str, str]]:
    """Grants implied by configured servers, plus each server's launch command.

    The alias is chosen by whoever wrote the config and carries no meaning; the
    package it launches does.
    """
    names: list[str] = []
    hints: dict[str, str] = {}
    for key in ("mcpServers", "servers", "mcp"):
        block = target.data.get(key)
        if not isinstance(block, dict):
            continue
        for alias, config in block.items():
            names.append(f"mcp__{alias}")
            if isinstance(config, dict):
                parts = [str(config.get("command", "")), str(config.get("url", ""))]
                parts += [str(a) for a in as_list(config.get("args"))]
                hints[alias.lower()] = " ".join(p for p in parts if p)
        break
    return names, hints


def collect_principals(targets: list[Target]) -> dict[str, dict]:
    """Group config into principals: one per subagent, one per project.

    A subagent is its own principal because its tool list replaces the parent's.
    Everything else in a project accumulates onto the project's main agent.

    ``permissions.deny`` is project-wide, so it is collected per project root and
    applied to every principal underneath it — a subagent cannot use a tool the
    project has denied, and reporting otherwise would over-report.
    """
    principals: dict[str, dict] = {}
    project_denies: dict[str, list[DenyList]] = {}

    for target in targets:
        root = project_root(target)

        if target.kind == AGENT_DEFINITION:
            name = str(target.data.get("name") or target.path.stem)
            declared = target.data.get("tools", target.data.get("allowed-tools"))
            if declared is None:
                # Inherits the parent's tools; MOAT-PERM-006 reports that
                # separately, and its true capability is the project's.
                continue
            key = f"{root}::agent:{name}"
            principals.setdefault(
                key,
                {"name": f"subagent '{name}'", "tools": [], "sources": [], "root": str(root), "hints": {}},
            )
            principals[key]["tools"].extend(as_list(declared))
            principals[key]["sources"].append(target)
            continue

        key = f"{root}::main"
        entry = principals.setdefault(
            key,
            {
                "name": f"main agent ({Path(root).name or root})",
                "tools": [],
                "sources": [],
                "root": str(root),
                "hints": {},
            },
        )
        entry["sources"].append(target)

        if target.kind == AGENT_SETTINGS:
            block = target.data.get("permissions")
            if isinstance(block, dict):
                entry["tools"].extend(as_list(block.get("allow")))
            names, hints = _server_names(target)
            entry["tools"].extend(names)
            entry["hints"].update(hints)
            project_denies.setdefault(str(root), []).append(_deny_list(target))
        elif target.kind == MCP_CONFIG:
            # Configuring a server grants every tool it exposes.
            names, hints = _server_names(target)
            entry["tools"].extend(names)
            entry["hints"].update(hints)

    for entry in principals.values():
        entry["deny"] = project_denies.get(entry["root"], [])
    return principals


@project_rule("MOAT-TRIFECTA-001", "Agent holds every capability needed to leak data")
def lethal_trifecta(targets: list[Target]) -> Iterator[Finding]:
    for entry in collect_principals(targets).values():
        denies: list[DenyList] = entry.get("deny", [])
        tools = [t for t in entry["tools"] if not any(d.blocks(t) for d in denies)]
        if not tools:
            continue
        _, breakdown = capabilities_of(tools, entry.get("hints"))
        total = Capability.NONE
        for tool, capability in list(breakdown.items()):
            for deny in denies:
                capability = deny.reduce(tool, capability)
            breakdown[tool] = capability
            total |= capability
        proof = witnesses(breakdown)
        anchor: Target = entry["sources"][0]

        if total & ALL_THREE == ALL_THREE:
            chain = " → ".join(
                f"{_LABELS[cap]} (`{proof[cap]}`)" for cap in ("private_data", "untrusted_input", "exfil")
            )
            yield Finding(
                rule_id="MOAT-TRIFECTA-001",
                title=f"{entry['name']} can read private data, ingest untrusted text and send it out",
                severity=Severity.CRITICAL,
                path=anchor.path,
                line=1,
                impact=(
                    "This is a working exfiltration path that needs no vulnerability: "
                    f"{chain}. Any content the agent reads — a web page, a dependency "
                    "README, a pull-request comment — can carry instructions that walk "
                    "it, and the agent has standing permission for every step."
                ),
                remediation=(
                    "Break the chain for this principal. Usually the cheapest cut is "
                    "egress: pin web access to known hosts and remove blanket network "
                    "commands. Otherwise split the work — one agent that reads private "
                    "data with no network, another that handles untrusted content with "
                    "no repository access."
                ),
                evidence=", ".join(f"{cap}={tool}" for cap, tool in proof.items()),
                meta={
                    "principal": entry["name"],
                    "capabilities": total.names,
                    "witnesses": proof,
                    "tool_count": len(tools),
                    "sources": [str(t.path) for t in entry["sources"]],
                },
            )
            continue

        held = total & ALL_THREE
        if bin(held.value).count("1") == 2:
            missing = [c for c in ("private_data", "untrusted_input", "exfil") if c not in held.names]
            yield Finding(
                rule_id="MOAT-TRIFECTA-002",
                title=f"{entry['name']} holds two of the three capabilities that enable exfiltration",
                severity=Severity.LOW,
                path=anchor.path,
                line=1,
                impact=(
                    f"It can already {' and '.join(_LABELS[c] for c in held.names)}. "
                    f"Adding the ability to {_LABELS[missing[0]]} completes a leak path, "
                    "so treat that as a security decision rather than a convenience one."
                ),
                remediation=(
                    f"Keep this principal free of {_LABELS[missing[0]]} capability, and "
                    "record why in the config so a later change does not silently close "
                    "the loop."
                ),
                evidence=", ".join(f"{cap}={tool}" for cap, tool in proof.items()),
                meta={"principal": entry["name"], "capabilities": held.names, "missing": missing},
            )
