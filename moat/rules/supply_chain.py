"""Where an MCP server's code comes from.

An MCP server is not a document the agent reads — it is a program that starts on
your machine, with your environment, every time the host launches. The launch
command in ``.mcp.json`` is therefore a build step nobody reviews, and it is
usually written to fetch the newest published version at every start.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..loader import as_list
from ..models import MCP_CONFIG, Finding, Severity, Target
from . import rule

KINDS = (MCP_CONFIG,)

#: Runners that resolve a package name over the network at launch time.
FETCHING_RUNNERS = {"npx", "uvx", "pipx", "bunx", "pnpx", "dlx"}

_PINNED = re.compile(r"@(?:\d+\.\d+|\^|~|latest\b)|==\d|@[0-9a-f]{40}$")
_PIPE_TO_SHELL = re.compile(r"(?:curl|wget)[^|;]*\|\s*(?:sudo\s+)?(?:ba|z|k|fi)?sh")


def _servers(target: Target) -> Iterator[tuple[str, dict]]:
    for key in ("mcpServers", "servers", "mcp"):
        block = target.data.get(key)
        if isinstance(block, dict):
            for name, config in block.items():
                if isinstance(config, dict):
                    yield name, config
            return


def _command_line(config: dict) -> str:
    parts = [str(config.get("command", ""))] + [str(a) for a in as_list(config.get("args"))]
    return " ".join(p for p in parts if p).strip()


@rule("MOAT-SUPPLY-001", "MCP server pulls an unpinned package at every launch", KINDS)
def unpinned_package(target: Target) -> Iterator[Finding]:
    for name, config in _servers(target):
        command = str(config.get("command", "")).rsplit("/", 1)[-1].lower()
        if command not in FETCHING_RUNNERS:
            continue
        args = [a for a in as_list(config.get("args")) if not a.startswith("-")]
        package = args[0] if args else ""
        if not package or _PINNED.search(package):
            continue
        yield Finding(
            rule_id="MOAT-SUPPLY-001",
            title=f"Server '{name}' runs `{command} {package}` with no version pin",
            severity=Severity.HIGH,
            path=target.path,
            line=target.locate(package),
            impact=(
                "Whatever the registry serves at launch runs with your shell's "
                "privileges and your environment. A single compromised release — "
                "or a maintainer handover — executes on every developer machine "
                "the next time the host starts, with no review and no diff."
            ),
            remediation=(
                f"Pin the exact version (`{package}@1.2.3`) and update deliberately. "
                "For anything holding real credentials, vendor the server and run it "
                "from a path you control."
            ),
            evidence=_command_line(config),
            meta={"server": name, "package": package, "runner": command},
        )


@rule("MOAT-SUPPLY-002", "MCP server installed from an unverifiable source", KINDS)
def untrusted_source(target: Target) -> Iterator[Finding]:
    for name, config in _servers(target):
        command_line = _command_line(config)
        lowered = command_line.lower()

        if _PIPE_TO_SHELL.search(lowered):
            yield Finding(
                rule_id="MOAT-SUPPLY-002",
                title=f"Server '{name}' pipes a downloaded script straight into a shell",
                severity=Severity.CRITICAL,
                path=target.path,
                line=target.locate("curl") or target.locate("wget"),
                impact=(
                    "The remote host decides what code runs on your machine, every "
                    "launch, and can serve different content to different clients."
                ),
                remediation="Download, review and vendor the installer, or use a signed package.",
                evidence=command_line,
                meta={"server": name},
            )
            continue

        for source in re.findall(r"(?:git\+|https?://)\S+|\S+\.(?:tgz|tar\.gz|zip)\b", command_line):
            if source.startswith("http://"):
                severity, why = Severity.CRITICAL, "over plain HTTP, so any network position can replace it"
            elif source.startswith("git+") or "github.com" in source:
                severity, why = Severity.MEDIUM, "from a git ref rather than a signed release"
            else:
                severity, why = Severity.MEDIUM, "from a direct archive URL that no registry verifies"
            yield Finding(
                rule_id="MOAT-SUPPLY-002",
                title=f"Server '{name}' is installed {why}",
                severity=severity,
                path=target.path,
                line=target.locate(source[:40]),
                impact="Code from this source executes locally with no integrity check.",
                remediation="Install from a package registry with a pinned version, over HTTPS.",
                evidence=command_line,
                meta={"server": name, "source": source},
            )
            break


@rule("MOAT-SUPPLY-003", "Remote MCP server reached over an insecure transport", KINDS)
def insecure_transport(target: Target) -> Iterator[Finding]:
    for name, config in _servers(target):
        url = str(config.get("url") or config.get("endpoint") or "")
        if not url.lower().startswith("http://"):
            continue
        local = re.match(r"http://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:/|$)", url, re.I)
        yield Finding(
            rule_id="MOAT-SUPPLY-003",
            title=f"Server '{name}' is contacted over plain HTTP",
            severity=Severity.LOW if local else Severity.HIGH,
            path=target.path,
            line=target.locate(url[:40]),
            impact=(
                "Loopback traffic stays on the machine, but any other local process "
                "can bind the port first and impersonate the server."
                if local
                else "Every tool call and result — including credentials passed as "
                "arguments — crosses the network in clear text, and the responses "
                "that steer the agent can be rewritten in transit."
            ),
            remediation="Use https:// and verify the certificate." if not local else "Prefer a stdio transport for local servers.",
            evidence=url,
            meta={"server": name, "loopback": bool(local)},
        )


@rule("MOAT-SUPPLY-004", "MCP server inherits the full environment", KINDS)
def env_passthrough(target: Target) -> Iterator[Finding]:
    for name, config in _servers(target):
        env = config.get("env")
        if not isinstance(env, dict):
            continue
        for key, value in env.items():
            if not isinstance(value, str):
                continue
            if value.strip() in ("*", "${*}") or re.fullmatch(r"\$\{?(?:ENV|ALL|.*\*)\}?", value.strip()):
                yield Finding(
                    rule_id="MOAT-SUPPLY-004",
                    title=f"Server '{name}' is handed the entire environment via `{key}`",
                    severity=Severity.HIGH,
                    path=target.path,
                    line=target.locate(key),
                    impact=(
                        "Third-party server code receives every variable in the "
                        "session, including credentials for unrelated systems."
                    ),
                    remediation="Pass only the specific variables the server documents.",
                    evidence=f"{key}: {value}",
                    meta={"server": name},
                )
