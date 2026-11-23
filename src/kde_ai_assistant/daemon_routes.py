"""What each daemon endpoint does, separated from HTTP mechanics.

``daemon_http`` authenticates a request, parses it, and looks the endpoint up
in ``ROUTES``; the functions here do the work and return ``(status, payload)``.
They receive the ``AssistantServer`` (for its state, settings and tool-server
manager), the parsed query string and the JSON body. They never touch the
socket.

Endpoints:

- ``GET /health``: daemon status plus which parts of setup are complete.
- ``GET /context``: desktop context capture (``desktop_context``).
- ``GET /search?q=...``: instant file search through the ``file_search`` role.
- ``GET /settings`` / ``PUT /settings``: read (redacted) and replace settings.
- ``GET /tools/discover``: tool servers found in other programs' configs.
- ``POST /tools/import``: copy one discovered server into the settings.
- ``GET /tools/servers``: configured servers, their tools and role proposals.
  This starts the servers, so it can take seconds.
- ``POST /open``: open a file, folder or link (``desktop_actions``).
- ``POST /models/probe``: list the models a service offers, to help setup.
- ``POST /models/test``: check that a configured model answers and can call
  tools. This sends one small request to the model.
- ``POST /cancel``: stop a conversation's running turn.
- ``POST /approve``: the user's answer to an approval request
  (``{"id", "decision": "allow"|"deny", "remember": bool}``).
- ``POST /screenshot``.

``POST /ask`` is not here: it streams, so ``daemon_http`` hands it to
``ask_stream``.

Errors the user can act on are returned as ``{"ok": false, "error": ...,
"code": ...}`` with a 4xx/5xx status; ``code`` lets the applet choose a fix
to offer (``not_configured``, ``tool_failed``, ``invalid``).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable

from . import desktop_actions, desktop_context, instant_search, mcp_discovery, settings as settings_store
from .agent_loop import user_folders
from .conversation import Message, TextDelta, ToolCallReady, ToolSpec
from .mcp_client import McpError
from .providers import ProviderError, create_provider
from .providers.openai_compatible import list_models
from .tool_roles import RoleNotConfigured, propose_role

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

Reply = tuple[int, dict[str, Any]]
Route = Callable[["AssistantServer", dict[str, list[str]], dict[str, Any]], Reply]

MAX_QUERY_CHARS = 500


def _error(status: int, message: str, code: str) -> Reply:
    return status, {"ok": False, "error": message, "code": code}


def _first(query: dict[str, list[str]], name: str, default: str = "") -> str:
    return (query.get(name) or [default])[0]


def health(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    payload = server.state.as_dict()
    roles = server.settings.get("roles", {})
    payload["setup"] = {
        "file_search": "file_search" in roles,
        "web_search": "web_search" in roles,
        "model": settings_store.active_model(server.settings) is not None,
    }
    payload["settings_error"] = server.settings_error
    return 200, payload


def context(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    kind = _first(query, "kind", "combined")
    captured = desktop_context.combined_context(kind)
    server.state.update(last_context_kind=kind)
    return 200, {"ok": True, "context": captured}


def search(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    text = _first(query, "q").strip()[:MAX_QUERY_CHARS]
    if not text:
        return 200, {"ok": True, "query": "", "hits": []}
    try:
        limit = max(1, min(instant_search.MAX_HITS, int(_first(query, "limit", "8"))))
    except ValueError:
        return _error(400, "limit must be a number", "invalid")
    try:
        hits = instant_search.search_files(server.mcp, server.settings, text, limit)
    except RoleNotConfigured:
        return _error(409, "File search is not set up yet.", "not_configured")
    except McpError as exc:
        return _error(502, str(exc), "tool_failed")
    return 200, {"ok": True, "query": text, "hits": hits}


def get_settings(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    # ``effective_folders`` is read-only information for the settings UI: where
    # each standard folder currently resolves to, overrides included.
    return 200, {
        "ok": True,
        "settings": settings_store.redacted(server.settings),
        "effective_folders": user_folders(server.settings.get("folders")),
    }


def put_settings(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        stored = server.replace_settings(settings_store.merge_redacted(body.get("settings"), server.settings))
    except settings_store.SettingsError as exc:
        return _error(400, str(exc), "invalid")
    return 200, {"ok": True, "settings": settings_store.redacted(stored)}


def discover_tools(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    configured = {
        (entry["command"], tuple(entry["args"])): name for name, entry in server.settings["tool_servers"].items()
    }
    found = []
    for candidate in mcp_discovery.discover_servers():
        described = candidate.describe()
        described["configured_as"] = configured.get((candidate.command, candidate.args))
        found.append(described)
    return 200, {"ok": True, "servers": found}


def import_tool_server(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    name = str(body.get("name") or "")
    source_path = str(body.get("source_path") or "")
    matches = [
        candidate
        for candidate in mcp_discovery.discover_servers()
        if candidate.name == name and (not source_path or candidate.source_path == source_path)
    ]
    if not matches:
        return _error(404, f"no tool server named '{name}' was found to import", "invalid")
    target = str(body.get("as") or name)
    updated = {**server.settings, "tool_servers": dict(server.settings["tool_servers"])}
    updated["tool_servers"][target] = matches[0].as_settings_entry(read_only=bool(body.get("read_only", False)))
    try:
        stored = server.replace_settings(updated)
    except settings_store.SettingsError as exc:
        return _error(400, str(exc), "invalid")
    return 200, {"ok": True, "imported": target, "settings": settings_store.redacted(stored)}


def list_tool_servers(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    only = _first(query, "name")
    servers = []
    for name, entry in sorted(server.settings["tool_servers"].items()):
        if only and name != only:
            continue
        item: dict[str, Any] = {
            "name": name,
            "enabled": entry["enabled"],
            "read_only": entry["read_only"],
            "tools": [],
            "proposals": [],
            "error": "",
        }
        if entry["enabled"]:
            try:
                tools = server.mcp.list_tools(name)
            except McpError as exc:
                item["error"] = str(exc)
            else:
                item["tools"] = [
                    {"name": tool["name"], "description": str(tool.get("description") or "")[:300]} for tool in tools
                ]
                item["proposals"] = [found for found in (propose_role(name, tool) for tool in tools) if found]
        servers.append(item)
    return 200, {"ok": True, "servers": servers}


def open_location(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        desktop_actions.open_location(str(body.get("location") or ""))
    except desktop_actions.DesktopActionError as exc:
        return _error(400, str(exc), "invalid")
    return 200, {"ok": True}


def screenshot(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, desktop_context.take_screenshot(server.runtime_dir)


def probe_models(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """List models at ``base_url``, also trying ``<base_url>/v1`` so a bare address works."""
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        return _error(400, "The address must start with http:// or https://", "invalid")
    api_key = body.get("api_key")
    if api_key is None and body.get("name"):
        api_key = server.settings.get("models", {}).get(str(body["name"]), {}).get("api_key", "")
    headers = body.get("headers") if isinstance(body.get("headers"), dict) else {}
    headers = {str(key): str(value) for key, value in headers.items()}
    candidates = [base_url] if base_url.endswith("/v1") else [base_url, f"{base_url}/v1"]
    failure = ""
    for candidate in candidates:
        try:
            models = list_models(candidate, str(api_key or ""), headers=headers)
        except ProviderError as exc:
            failure = failure or str(exc)
            continue
        return 200, {"ok": True, "base_url": candidate, "models": models}
    return _error(502, failure, "unreachable")


def test_model(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Ask the named (or active) model to call a trivial tool; report whether it did."""
    name = str(body.get("name") or server.settings.get("active_model") or "")
    model = server.settings.get("models", {}).get(name)
    if model is None:
        return _error(404, f"no model named '{name}' is set up", "invalid")
    probe_tool = ToolSpec("confirm_ready", "Call this to confirm you can use tools.",
                          {"type": "object", "properties": {}, "required": []})
    messages = [
        Message("system", "You are being tested. Call the confirm_ready tool. Do not reply with text."),
        Message("user", "Call confirm_ready now."),
    ]
    called, text = False, ""
    try:
        for event in create_provider(model).stream(messages, [probe_tool], threading.Event()):
            if isinstance(event, ToolCallReady) and event.call.name == "confirm_ready":
                called = True
            elif isinstance(event, TextDelta):
                text += event.text
    except ProviderError as exc:
        return _error(502, str(exc), "unreachable")
    if not called:
        return 200, {"ok": True, "name": name, "answers": True, "tools": False, "reply": text[:200]}
    return 200, {"ok": True, "name": name, "answers": True, "tools": True}


def cancel(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "cancelled": server.conversations.cancel(str(body.get("conversation_id") or ""))}


def approve(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    accepted = server.approvals.resolve(
        str(body.get("id") or ""), str(body.get("decision") or ""), bool(body.get("remember", False)))
    if not accepted:
        return _error(404, "That request is no longer waiting for an answer.", "invalid")
    return 200, {"ok": True}


ROUTES: dict[tuple[str, str], Route] = {
    ("GET", "/health"): health,
    ("GET", "/context"): context,
    ("GET", "/search"): search,
    ("GET", "/settings"): get_settings,
    ("PUT", "/settings"): put_settings,
    ("GET", "/tools/discover"): discover_tools,
    ("POST", "/tools/import"): import_tool_server,
    ("GET", "/tools/servers"): list_tool_servers,
    ("POST", "/open"): open_location,
    ("POST", "/screenshot"): screenshot,
    ("POST", "/models/probe"): probe_models,
    ("POST", "/models/test"): test_model,
    ("POST", "/cancel"): cancel,
    ("POST", "/approve"): approve,
}
