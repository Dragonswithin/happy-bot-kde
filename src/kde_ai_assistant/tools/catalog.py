"""Assembles the set of tools offered to the model for a turn.

The catalogue is every built-in tool (reading the desktop, windows,
applications, system controls, files, the shell) followed by the tools of the
user's MCP servers. Built-in names win a clash. Which calls may run without
asking is not decided here: every tool is offered, and the permission gate
judges each call.
"""

from __future__ import annotations

from typing import Any

from ..mcp_client import McpManager
from .apps import app_tools
from .files import file_tools
from .mcp_bridge import mcp_tools
from .observe import observe_tools
from .registry import Tool, ToolRegistry
from .shell import shell_tools
from .system import system_tools
from .windows import window_tools


def builtin_tools() -> list[Tool]:
    return [*observe_tools(), *window_tools(), *app_tools(), *system_tools(), *file_tools(), *shell_tools()]


def build_registry(manager: McpManager, settings: dict[str, Any]) -> tuple[ToolRegistry, list[str]]:
    """Return the registry for a turn and any warnings about tool servers that could not be reached."""
    bridged, warnings = mcp_tools(manager, settings)
    selected: list[Tool] = []
    seen: set[str] = set()
    for tool in [*builtin_tools(), *bridged]:
        if tool.name not in seen:
            seen.add(tool.name)
            selected.append(tool)
    return ToolRegistry(selected), warnings
