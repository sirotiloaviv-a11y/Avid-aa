"""Finding the files that grant an agent its powers.

The blast radius of an AI agent is decided by a handful of small files that
almost nobody reviews: where its MCP servers come from, which tools are
pre-approved, and which shell commands fire automatically. This module locates
them across the hosts people actually use.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .loader import load_frontmatter, load_json
from .models import (
    AGENT_DEFINITION,
    AGENT_SETTINGS,
    MCP_CONFIG,
    SKILL_DEFINITION,
    Target,
)

#: Exact filenames that describe MCP servers, whatever the host.
MCP_FILENAMES = {
    ".mcp.json",
    "mcp.json",
    "claude_desktop_config.json",
    "mcp_settings.json",
    "cline_mcp_settings.json",
}

#: Settings files that carry permissions, hooks and environment.
SETTINGS_FILENAMES = {
    "settings.json",
    "settings.local.json",
}

#: Directories that never contain hand-written agent config and are large.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    "vendor",
    "target",
}

MAX_BYTES = 2 * 1024 * 1024


def classify(path: Path) -> str | None:
    """Return the target kind for a path, or None if it is not agent config."""
    name = path.name
    parts = path.parts

    if name in MCP_FILENAMES:
        return MCP_CONFIG
    if name in SETTINGS_FILENAMES and ".claude" in parts:
        return AGENT_SETTINGS
    # Cursor and VS Code keep MCP servers in their own settings file.
    if name in SETTINGS_FILENAMES and (".cursor" in parts or ".vscode" in parts):
        return MCP_CONFIG
    if name.endswith(".md") and "agents" in parts and ".claude" in parts:
        return AGENT_DEFINITION
    if name == "SKILL.md":
        return SKILL_DEFINITION
    return None


def _excluded(path: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    """Match a pattern against the path, both absolute and root-relative.

    Matching both forms means `--exclude examples/*` works from the repo root
    without the caller having to know how the path was spelled.
    """
    if not patterns:
        return False
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = path
    candidates = (path.as_posix(), relative.as_posix(), *(p.as_posix() for p in relative.parents))
    return any(
        fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(candidate, f"{pattern}/*")
        for pattern in patterns
        for candidate in candidates
    )


def discover(root: Path, exclude: tuple[str, ...] = ()) -> list[Path]:
    """Walk ``root`` and return every agent-config path, sorted."""
    root = Path(root)
    if root.is_file():
        return [root] if classify(root) and not _excluded(root, root, exclude) else []

    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
                continue
            if classify(entry) and not _excluded(entry, root, exclude):
                found.append(entry)
    return sorted(found)


def load_target(path: Path) -> Target | None:
    """Read and parse one config file into a Target."""
    kind = classify(path)
    if kind is None:
        return None
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if kind in (AGENT_DEFINITION, SKILL_DEFINITION):
        data, body = load_frontmatter(raw)
        return Target(path=path, kind=kind, raw=raw, data=data, body=body)

    data, error = load_json(raw)
    return Target(path=path, kind=kind, raw=raw, data=data, parse_error=error)


def collect(root: Path, exclude: tuple[str, ...] = ()) -> list[Target]:
    """Discover and parse everything under ``root``."""
    targets = []
    for path in discover(root, exclude):
        target = load_target(path)
        if target is not None:
            targets.append(target)
    return targets
