"""Finds tool servers the user already configured for other AI programs.

Setup offers to import existing MCP servers instead of making the user type
launch commands. This module reads the configuration files of common agent
programs, read-only, and returns the stdio servers defined in them. It never
starts a server and never writes anything.

Formats are parsed best-effort: a file that is missing, unreadable or shaped
differently than expected contributes nothing. Any JSON or TOML object that
maps names to entries with a ``command`` is accepted, which covers the
``mcpServers`` convention and its variants (``servers``, ``mcp``,
``mcp_servers``), including a ``command`` given as a list. Remote (URL-only)
servers are skipped because the daemon speaks stdio only.

Environment values are read so an import can carry them into the assistant's
own settings, but ``describe`` omits them: clients see variable names only.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVER_MAP_KEYS = ("mcpServers", "mcp_servers", "servers", "mcp")
ENV_KEYS = ("env", "environment")
# (label shown to the user, path relative to the home directory)
KNOWN_CONFIG_FILES = (
    ("Claude Code", ".claude.json"),
    ("Claude Desktop", ".config/Claude/claude_desktop_config.json"),
    ("Codex", ".codex/config.toml"),
    ("Cursor", ".cursor/mcp.json"),
    ("Gemini CLI", ".gemini/settings.json"),
    ("OpenCode", ".config/opencode/opencode.json"),
    ("VS Code", ".config/Code/User/mcp.json"),
    ("Windsurf", ".codeium/windsurf/mcp_config.json"),
)


@dataclass(frozen=True)
class DiscoveredServer:
    name: str
    source: str
    source_path: str
    command: str
    args: tuple[str, ...]
    env: tuple[tuple[str, str], ...]

    def describe(self) -> dict[str, Any]:
        """Client-safe form: environment variable names without values."""
        return {
            "name": self.name,
            "source": self.source,
            "source_path": self.source_path,
            "command": self.command,
            "args": list(self.args),
            "env_names": [name for name, _ in self.env],
        }

    def as_settings_entry(self, read_only: bool) -> dict[str, Any]:
        return {
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "enabled": True,
            "read_only": read_only,
            "tools": None,
        }


def _parse_entry(name: str, entry: Any, source: str, path: Path) -> DiscoveredServer | None:
    if not isinstance(entry, dict) or entry.get("disabled") is True or entry.get("enabled") is False:
        return None
    command = entry.get("command")
    args = entry.get("args", [])
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        command, args = command[0], [*command[1:], *(args if isinstance(args, list) else [])]
    if not isinstance(command, str) or not command.strip():
        return None
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        return None
    env: dict[str, str] = {}
    for key in ENV_KEYS:
        value = entry.get(key)
        if isinstance(value, dict):
            env.update({str(k): str(v) for k, v in value.items() if isinstance(v, (str, int, float))})
    return DiscoveredServer(name, source, str(path), command.strip(), tuple(args), tuple(sorted(env.items())))


def _server_maps(document: Any) -> list[dict[str, Any]]:
    """Top-level server maps, plus Claude Code's per-project ones."""
    if not isinstance(document, dict):
        return []
    maps = [document[key] for key in SERVER_MAP_KEYS if isinstance(document.get(key), dict)]
    projects = document.get("projects")
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict) and isinstance(project.get("mcpServers"), dict):
                maps.append(project["mcpServers"])
    return maps


def _read_document(path: Path) -> Any:
    try:
        raw = path.read_bytes()
        return tomllib.loads(raw.decode("utf-8")) if path.suffix == ".toml" else json.loads(raw)
    except (OSError, ValueError):
        return None


def discover_servers(home: Path | None = None) -> list[DiscoveredServer]:
    """Return stdio servers from known agent configs; the first definition of a launch command wins."""
    base = home or Path.home()
    found: list[DiscoveredServer] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for source, relative in KNOWN_CONFIG_FILES:
        path = base / relative
        for server_map in _server_maps(_read_document(path)):
            for name, entry in server_map.items():
                server = _parse_entry(str(name), entry, source, path)
                if server is None or (server.command, server.args) in seen:
                    continue
                seen.add((server.command, server.args))
                found.append(server)
    return found
