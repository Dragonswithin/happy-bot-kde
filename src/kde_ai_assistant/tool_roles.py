"""Roles: which of the user's tools the assistant uses for a known job.

A tool server exposes arbitrary tools. Two jobs need a specific one: the
search bar's instant file search (``file_search``) and answering from the web
(``web_search``). A role in the settings names the server and tool and says
which argument receives the user's text. This module turns a role plus a
query into a tool call, helps setup by proposing role assignments from a
tool's name, description and input schema, and lists a tool's arguments so
the settings page can let the user pick the query argument by hand.

The proposals are heuristics over wording ("search", "file", "web"); they are
shown to the user as suggestions and never applied on their own. No specific
index, search engine or server name is known here.
"""

from __future__ import annotations

import re
from typing import Any

from .mcp_client import McpManager, ToolResult

QUERY_ARGUMENT_NAMES = ("query", "q", "search", "text", "keywords", "term", "prompt")
LIMIT_ARGUMENT_NAMES = ("limit", "max_results", "top_k", "k", "count", "num_results", "n")
DEFAULT_RESULT_LIMIT = 8
# Whole words that mark a search tool as being about the user's own files or
# about the web. "local" and "path" are deliberately absent: offline
# reference archives and many other tools use them without searching files.
_ROLE_WORDS = {
    "file_search": ("file", "files", "document", "documents", "disk", "filesystem", "folder", "folders"),
    "web_search": ("web", "internet", "online", "searx", "searxng", "google", "bing", "duckduckgo", "brave", "news"),
}


class RoleNotConfigured(LookupError):
    """The requested role has no tool assigned."""


def _properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema")
    properties = schema.get("properties") if isinstance(schema, dict) else None
    return properties if isinstance(properties, dict) else {}


def tool_arguments(tool: dict[str, Any]) -> list[dict[str, Any]]:
    """The tool's arguments as ``{"name", "type", "required"}``, for the settings page's role editor."""
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    required = set(schema.get("required", [])) if isinstance(schema.get("required"), list) else set()
    return [
        {"name": name, "type": str(spec.get("type", "")) if isinstance(spec, dict) else "", "required": name in required}
        for name, spec in _properties(tool).items()
    ]


def find_query_argument(tool: dict[str, Any]) -> str | None:
    """Name of the tool's free-text argument, or None if it has no obvious one."""
    properties = _properties(tool)
    strings = [name for name, spec in properties.items() if isinstance(spec, dict) and spec.get("type") == "string"]
    for candidate in QUERY_ARGUMENT_NAMES:
        if candidate in strings:
            return candidate
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    required = [name for name in schema.get("required", []) if name in strings]
    return required[0] if len(required) == 1 else None


def find_limit_argument(tool: dict[str, Any]) -> str | None:
    properties = _properties(tool)
    for candidate in LIMIT_ARGUMENT_NAMES:
        spec = properties.get(candidate)
        if isinstance(spec, dict) and spec.get("type") in ("integer", "number"):
            return candidate
    return None


def propose_role(server: str, tool: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``{"role", "config"}`` if ``tool`` looks like a file or web search, else None.

    A tool qualifies only if all its required arguments are covered by the
    single query argument, so the proposed configuration is callable as is.
    """
    query_argument = find_query_argument(tool)
    if query_argument is None:
        return None
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    if any(name != query_argument for name in schema.get("required", [])):
        return None
    wording = f"{tool.get('name', '')} {tool.get('description', '')}".lower()
    if "search" not in wording and "find" not in wording:
        return None
    found = set(re.findall(r"[a-z]+", wording))
    scores = {role: len(found.intersection(words)) for role, words in _ROLE_WORDS.items()}
    role = max(scores, key=lambda name: scores[name])
    if scores[role] == 0 or list(scores.values()).count(scores[role]) > 1:
        return None
    arguments: dict[str, Any] = {}
    limit_argument = find_limit_argument(tool)
    if limit_argument:
        arguments[limit_argument] = DEFAULT_RESULT_LIMIT
    return {
        "role": role,
        "config": {"server": server, "tool": tool["name"], "query_argument": query_argument, "arguments": arguments},
    }


def call_role(
    manager: McpManager,
    settings: dict[str, Any],
    role: str,
    query: str,
    timeout: float,
) -> ToolResult:
    """Run the tool assigned to ``role`` with ``query``. Raises ``RoleNotConfigured`` or ``McpError``."""
    config = settings.get("roles", {}).get(role)
    if not config:
        raise RoleNotConfigured(role)
    arguments = {**config.get("arguments", {}), config["query_argument"]: query}
    return manager.call_tool(config["server"], config["tool"], arguments, timeout)
