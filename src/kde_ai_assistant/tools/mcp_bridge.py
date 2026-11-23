"""Exposes the user's MCP tool servers as assistant tools, and builds the registry.

For each enabled tool server this lists its tools and wraps each one as a
``Tool`` whose handler forwards the call through ``McpManager``. A bridged
tool is named ``<server>__<tool>`` (other characters become ``_``, capped at
64) so two servers can offer tools with the same name.

Risk comes from what the user declared, because a server's own description
of its tools cannot be trusted for this: tools of a server marked
``read_only`` and the tools assigned to the ``file_search`` / ``web_search``
roles are ``read``; every other bridged tool is ``change``. A server's
optional ``tools`` allow-list in the settings hides everything else.

A server that fails to start does not fail the turn: its tools are simply
absent and the reason is returned in ``warnings`` for the user.

``build_registry`` assembles the built-in tools plus bridged ones, keeping
only tools whose risk is in ``allowed_risks``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..mcp_client import McpError, McpManager
from .observe import observe_tools
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, ToolRegistry, object_schema

MCP_CALL_TIMEOUT_SECONDS = 90.0
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def bridged_name(server: str, tool: str) -> str:
    return _UNSAFE.sub("_", f"{server}__{tool}")[:64]


def _make_handler(manager: McpManager, server: str, tool: str):
    def handler(arguments: dict[str, Any]) -> str:
        try:
            result = manager.call_tool(server, tool, arguments, MCP_CALL_TIMEOUT_SECONDS)
        except McpError as error:
            raise ToolFailure(str(error)) from error
        text = result.text
        if not text.strip() and result.structured is not None:
            text = json.dumps(result.structured, ensure_ascii=False)
        if result.is_error:
            raise ToolFailure(text or "the tool reported an error")
        return text

    return handler


def mcp_tools(manager: McpManager, settings: dict[str, Any]) -> tuple[list[Tool], list[str]]:
    """Return ``(tools, warnings)`` for every enabled tool server."""
    role_tools = {(role["server"], role["tool"]): name for name, role in settings.get("roles", {}).items()}
    tools: list[Tool] = []
    warnings: list[str] = []
    for server, entry in sorted(settings.get("tool_servers", {}).items()):
        if not entry.get("enabled", True):
            continue
        try:
            listed = manager.list_tools(server)
        except McpError as error:
            warnings.append(str(error))
            continue
        allowed = entry.get("tools")
        for item in listed:
            name = item["name"]
            if allowed is not None and name not in allowed:
                continue
            role = role_tools.get((server, name))
            description = str(item.get("description") or name).strip()
            if role == "file_search":
                description = "Preferred tool for finding the user's local files and documents. " + description
            elif role == "web_search":
                description = "Preferred tool for current information from the web. " + description
            schema = item.get("inputSchema")
            tools.append(Tool(
                name=bridged_name(server, name),
                description=description[:1000],
                parameters=schema if isinstance(schema, dict) and schema.get("type") == "object" else object_schema(),
                risk=RISK_READ if (entry.get("read_only") or role) else RISK_CHANGE,
                handler=_make_handler(manager, server, name),
                source=server,
            ))
    return tools, warnings


def build_registry(
    manager: McpManager,
    settings: dict[str, Any],
    allowed_risks: tuple[str, ...],
) -> tuple[ToolRegistry, list[str]]:
    """Assemble built-in and bridged tools limited to ``allowed_risks``."""
    bridged, warnings = mcp_tools(manager, settings)
    selected: list[Tool] = []
    seen: set[str] = set()
    for tool in [*observe_tools(), *bridged]:
        if tool.risk in allowed_risks and tool.name not in seen:
            seen.add(tool.name)
            selected.append(tool)
    return ToolRegistry(selected), warnings
