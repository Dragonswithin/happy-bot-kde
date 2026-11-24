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
  The read also carries what the settings page needs to offer choices:
  ``effective_folders`` (where each standard folder is now) and
  ``terminals`` (supported terminals that are installed) and
  ``suggested_instructions`` (the default text of ``agent.instructions``).
- ``GET /tools/discover``: tool servers found in other programs' configs.
- ``POST /tools/import``: copy one discovered server into the settings.
- ``GET /tools/servers[?name=...]``: configured servers, their tools (with
  each tool's arguments and its likely query and result-limit arguments) and
  role proposals. This starts the servers, so it
  can take seconds.
- ``POST /open``: open a file, folder or link (``desktop_actions``).
- ``POST /models/discover``: find model services running on this computer.
- ``POST /tools/scan``: start each discovered, not yet configured tool
  server briefly to report its tools and the roles it could fill. Slow by
  nature (seconds per server); servers are scanned in parallel
  (``search_choices.scan_discovered``).
- ``POST /search/choices``: what could do file search or web search here,
  best first, for the settings page's "Set up" (``search_choices``).
- ``POST /search/use``: use one of those choices: add its server, assign the
  job, run a test search, and undo it all if the test fails
  (``search_setup``). Can take a minute when a server is downloaded first.
- ``GET /typing``, ``POST /typing/allow``: whether the desktop allows the
  assistant to type into other apps, and asking it now (the RemoteDesktop
  portal's dialog, ``input_portal``) rather than in the middle of a request.
- ``POST /models/probe``: list the models a service offers, to help setup.
- ``POST /models/test``: check that a configured model answers and can call
  tools. This sends one small request to the model.
- ``POST /cancel``: stop a conversation's running turn.
- ``GET /conversations``: saved conversations, newest first
  (``{id, title, created, updated, requests}``).
- ``GET /conversation?id=...``: one conversation's display events, for the
  popup to redraw it.
- ``POST /conversations/delete``: ``{"id": ...}`` or ``{"all": true}``.
- ``POST /conversations/pin``: ``{"id": ..., "pinned": bool}``; pinned ones
  are listed first and kept past ``history_days``.
- ``GET /export`` / ``POST /import``: everything the assistant keeps for the
  user, without secrets (``personal_data``).
- ``GET /tools/catalog`` / ``POST /tools/run``: the built-in tools lent to
  other AI programs through ``happy-bot mcp-serve``, only while the
  user's ``agent.serve_tools`` setting is on. A call that the approval
  policy would put to the user is refused (there is no one to ask), and
  every call is written to the action log.
- ``GET /spend``: this month's tokens and cost per model (``spend``).
- ``GET /check``: the self-check (``self_check.run_checks``): every
  dependency's state with a fix for each problem.
- ``GET /quick?q=...``: results the bar shows besides files (answers,
  windows, applications, settings pages, conversations; ``quick_results``).
- ``POST /quick/activate``: ``{"action": {...}}`` from one of those results.
- ``GET /reminders``: reminders and timers that are set
  (``{id, when, text}``, soonest first; ``tools/reminders.py``).
- ``POST /reminders/cancel``: ``{"id": ...}``.
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

import json
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

from concurrent.futures import ThreadPoolExecutor

from . import (desktop_actions, desktop_context, input_portal, instant_search, mcp_discovery, model_discovery, personal_data,
               quick_results, search_choices, search_setup, self_check, spend)
from . import settings as settings_store
from .agent_loop import user_folders
from .conversation import Message, TextDelta, ToolCallReady, ToolSpec
from .mcp_client import McpError
from .providers import ProviderError, create_provider
from .providers.openai_compatible import list_models
from .tool_roles import RoleNotConfigured, find_limit_argument, find_query_argument, propose_role, tool_arguments
from .tools import reminders
from .tools.registry import ToolFailure
from .tools.shell import installed_terminals

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
        "terminals": installed_terminals(),
        "suggested_instructions": settings_store.SUGGESTED_INSTRUCTIONS,
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
                    {"name": tool["name"], "description": str(tool.get("description") or "")[:300],
                     "arguments": tool_arguments(tool), "query_argument": find_query_argument(tool) or "",
                     "limit_argument": find_limit_argument(tool) or ""}
                    for tool in tools
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


def discover_models(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    def key(base_url: str, model_id: str) -> tuple[str, str]:
        # The same service may be stored with or without its /v1 suffix.
        return base_url.rstrip("/").removesuffix("/v1"), model_id

    configured = {key(model["base_url"], model["model"]): name for name, model in server.settings["models"].items()}
    services = model_discovery.discover_local(skip_ports=(server.state.port,))
    for service in services:
        for model in service["models"]:
            model["configured_as"] = configured.get(key(service["base_url"], model["id"]))
    return 200, {"ok": True, "services": services}


def scan_tool_servers(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    configured = {(entry["command"], tuple(entry["args"])) for entry in server.settings["tool_servers"].values()}
    candidates = [c for c in mcp_discovery.discover_servers() if (c.command, c.args) not in configured]
    if not candidates:
        return 200, {"ok": True, "servers": []}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return 200, {"ok": True, "servers": list(pool.map(search_choices.scan_discovered, candidates))}


def search_choices_route(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    role = str(body.get("role") or "")
    if role not in settings_store.ROLE_NAMES:
        return _error(400, f"unknown job '{role}'", "invalid")
    return 200, {"ok": True, "choices": search_choices.choices(role, server.settings, skip_ports=(server.state.port,))}


def search_use(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
    result = search_setup.use(server, str(body.get("role") or ""), str(body.get("choice") or ""),
                              {str(key): str(value) for key, value in inputs.items()})
    if not result["ok"]:
        return _error(400, result["error"], "invalid")
    return 200, {**result, "settings": settings_store.redacted(server.settings)}


def typing_status(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "allowed": input_portal.consent_saved()}


def allow_typing(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    """Shows the desktop's "allow remote control" question now, instead of in the middle of a request."""
    try:
        input_portal.shared().start()
    except input_portal.InputUnavailable as error:
        return _error(409, str(error).capitalize() + ".", "declined")
    return 200, {"ok": True, "allowed": input_portal.consent_saved()}


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


def list_conversations(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "conversations": server.conversations.list()}


def get_conversation(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    conversation = server.conversations.get(_first(query, "id"))
    if conversation is None:
        return _error(404, "That conversation is no longer saved.", "invalid")
    return 200, {"ok": True, "id": conversation.id, "title": conversation.title, "events": conversation.events}


def delete_conversations(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if body.get("all") is True:
        return 200, {"ok": True, "deleted": server.conversations.delete_all()}
    if not server.conversations.delete(str(body.get("id") or "")):
        return _error(404, "That conversation is no longer saved.", "invalid")
    return 200, {"ok": True, "deleted": 1}


def pin_conversation(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if not server.conversations.set_pinned(str(body.get("id") or ""), body.get("pinned") is True):
        return _error(404, "That conversation is no longer saved.", "invalid")
    return 200, {"ok": True}


def approve(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    accepted = server.approvals.resolve(
        str(body.get("id") or ""), str(body.get("decision") or ""), bool(body.get("remember", False)))
    if not accepted:
        return _error(404, "That request is no longer waiting for an answer.", "invalid")
    return 200, {"ok": True}


def export(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, "data": personal_data.export_data(server)}


def import_(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, **personal_data.import_data(server, body.get("data"))}
    except (personal_data.BadExport, settings_store.SettingsError) as error:
        return _error(400, str(error), "invalid")


def _lent_tools(server: "AssistantServer"):
    from .tools.catalog import builtin_tools
    from .tools.registry import ToolRegistry

    return ToolRegistry(builtin_tools(server.settings.get("agent")))


def tool_catalog(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    if not server.settings["agent"].get("serve_tools"):
        return _error(403, "Lending tools to other programs is switched off in the assistant's settings.", "invalid")
    registry = _lent_tools(server)
    return 200, {"ok": True, "tools": [{"name": spec.name, "description": spec.description,
                                        "inputSchema": spec.parameters} for spec in registry.specs()]}


def run_tool(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    from .permissions import append_audit, needs_approval

    if not server.settings["agent"].get("serve_tools"):
        return _error(403, "Lending tools to other programs is switched off in the assistant's settings.", "invalid")
    name, arguments = str(body.get("name") or ""), body.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(400, "arguments must be an object", "invalid")
    registry = _lent_tools(server)
    if registry.get(name) is None:
        return _error(404, f"there is no tool named {name}", "invalid")
    risk, summary, detail = registry.assess(name, arguments)
    outcome = "refused for another program"
    if needs_approval(server.settings.get("approval_policy", "danger"), risk):
        result = (False, f"Refused: '{summary}' needs the user's approval ({detail or risk}), which can only be "
                         "given in the assistant's own bar.")
    else:
        impossible = registry.precheck(name, arguments)
        result = (False, impossible) if impossible else registry.run(name, arguments)
        outcome = "ran for another program"
    if risk != "read":
        append_audit(server.runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": name, "risk": risk,
                                          "outcome": outcome, "arguments": json.dumps(arguments)[:2000]})
    return 200, {"ok": True, "succeeded": result[0], "text": result[1]}


def spending(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    return 200, {"ok": True, **spend.month_summary()}


def check(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    results = self_check.run_checks(server)
    return 200, {"ok": True, "healthy": all(item["ok"] for item in results), "checks": results}


def quick(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    text = _first(query, "q").strip()[:MAX_QUERY_CHARS]
    return 200, {"ok": True, "query": text, "results": quick_results.gather(text, server.conversations.list())}


def quick_activate(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    action = body.get("action")
    if not isinstance(action, dict):
        return _error(400, "action is required", "invalid")
    try:
        return 200, {"ok": True, "message": quick_results.activate(action)}
    except quick_results.ActivationError as error:
        return _error(400, str(error), "invalid")


def list_reminders(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    items = reminders.upcoming()
    return 200, {"ok": True, "reminders": [
        {"id": item["id"], "when": item["when"].strftime("%Y-%m-%d %H:%M"), "text": item["text"]} for item in items]}


def cancel_reminder(server: "AssistantServer", query: dict[str, list[str]], body: dict[str, Any]) -> Reply:
    try:
        return 200, {"ok": True, "message": reminders.cancel_reminder({"id": str(body.get("id") or "")})}
    except ToolFailure as error:
        return _error(404, str(error), "invalid")


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
    ("POST", "/models/discover"): discover_models,
    ("POST", "/tools/scan"): scan_tool_servers,
    ("POST", "/search/choices"): search_choices_route,
    ("POST", "/search/use"): search_use,
    ("GET", "/typing"): typing_status,
    ("POST", "/typing/allow"): allow_typing,
    ("POST", "/models/test"): test_model,
    ("POST", "/cancel"): cancel,
    ("POST", "/approve"): approve,
    ("GET", "/conversations"): list_conversations,
    ("GET", "/conversation"): get_conversation,
    ("POST", "/conversations/delete"): delete_conversations,
    ("POST", "/conversations/pin"): pin_conversation,
    ("GET", "/check"): check,
    ("GET", "/spend"): spending,
    ("GET", "/tools/catalog"): tool_catalog,
    ("POST", "/tools/run"): run_tool,
    ("GET", "/export"): export,
    ("POST", "/import"): import_,
    ("GET", "/quick"): quick,
    ("POST", "/quick/activate"): quick_activate,
    ("GET", "/reminders"): list_reminders,
    ("POST", "/reminders/cancel"): cancel_reminder,
}
