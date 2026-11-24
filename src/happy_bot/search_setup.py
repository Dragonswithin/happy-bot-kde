"""Using one of setup's search choices: add its tool server, give it the job, and prove it works.

``POST /search/use`` calls ``use`` with a choice from ``search_choices.choices``. In order:

1. Build the tool-server entry and the role for the choice. A ``builtin`` choice runs
   ``happy-bot file-index-serve --index kde|locate`` (``file_index_server``); a ``found`` one is
   imported from the other AI program's configuration; a ``suggested`` one uses its pinned start
   command with what the user typed (an address or an API key) as its environment.
2. Switch KDE's file index on if the choice needs it (``balooctl6 enable``: the user's own KDE
   setting, no root).
3. Start the server once on its own with a generous ``FIRST_START_SECONDS``, because the first
   start of an ``npx``/``uvx`` server downloads it, and check that it offers the expected tool.
4. Save the server and role through ``AssistantServer.replace_settings`` (validated like any
   settings change), then run one test search through the role.

If step 3 or the test fails, the previous settings are put back and the plain reason is returned,
so a failed choice never leaves a half-set-up job behind. A test that works but finds nothing
still counts: a file index that was just switched on is still learning.

The result is ``{"ok": True, "server", "message"}`` or ``{"ok": False, "error"}``. This runs on the
request's thread and can take a minute on a first download; the settings page shows it as busy.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import mcp_discovery, search_choices
from . import settings as settings_store
from .mcp_client import McpError, McpServerSpec, McpSession
from .tool_roles import call_role, find_limit_argument

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

FIRST_START_SECONDS = 180.0
TEST_SECONDS = 60.0
BUILTIN_SERVER_NAMES = {"kde": "kde_file_search", "locate": "file_names"}


class ChoiceError(ValueError):
    """The choice cannot be used as given; the message is shown to the user."""


def _launcher() -> str:
    return shutil.which("happy-bot") or str(Path.home() / ".local" / "bin" / "happy-bot")


def _builtin(index: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if index == "kde" and search_choices.kde_index_state() == "off":
        try:
            subprocess.run(["balooctl6", "enable"], capture_output=True, text=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise ChoiceError("KDE's file search could not be switched on. Switch on File Search in System "
                              "Settings (Search), then try again.") from error
    entry = {"command": _launcher(), "args": ["file-index-serve", "--index", index], "env": {},
             "enabled": True, "read_only": True, "tools": None}
    role = {"tool": "find_files", "query_argument": "query", "arguments": {"limit": search_choices.RESULT_LIMIT}}
    return BUILTIN_SERVER_NAMES[index], entry, role


def _found(role_name: str, choice_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    _, name, source_path = choice_id.split(":", 2)
    candidate = next((c for c in mcp_discovery.discover_servers()
                      if c.name == name and c.source_path == source_path), None)
    if candidate is None:
        raise ChoiceError(f"{name} is no longer set up in the other program.")
    scanned = search_choices.scan_discovered(candidate)
    proposal = next((found for found in scanned["proposals"] if found["role"] == role_name), None)
    if proposal is None:
        raise ChoiceError(scanned["error"] or f"{name} no longer offers a search tool for this.")
    config = proposal["config"]
    role = {"tool": config["tool"], "query_argument": config["query_argument"], "arguments": config["arguments"]}
    return name, candidate.as_settings_entry(read_only=False), role


def _suggested(choice_id: str, inputs: dict[str, str]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    item = search_choices.suggestion(choice_id)
    if item is None:
        raise ChoiceError("That choice is not offered any more.")
    if not shutil.which(item["program"]):
        raise ChoiceError(f"Needs {search_choices.PROGRAM_HELP.get(item['program'], item['program'])} installed first.")
    env = {}
    for field in item["inputs"]:
        value = str(inputs.get(field["name"]) or "").strip()
        if not value:
            raise ChoiceError(f"Fill in {field['label']} first.")
        if field["name"].endswith("_URL") and not value.startswith(("http://", "https://")):
            raise ChoiceError(f"{field['label']} must start with http:// or https://")
        env[field["name"]] = value
    entry = {"command": item["command"], "args": list(item["args"]), "env": env,
             "enabled": True, "read_only": True, "tools": None}
    role = {"tool": item["tool"], "query_argument": "query", "arguments": dict(item["arguments"])}
    return item["id"], entry, role


def _free_name(wanted: str, entry: dict[str, Any], servers: dict[str, Any]) -> str:
    """``wanted``, or the name of an identical server already set up, or ``wanted_2``, ``wanted_3``..."""
    for name, existing in servers.items():
        if existing.get("command") == entry["command"] and list(existing.get("args", [])) == entry["args"]:
            return name
    name, number = wanted, 2
    while name in servers:
        name, number = f"{wanted}_{number}", number + 1
    return name


def _first_start(name: str, entry: dict[str, Any], tool: str) -> dict[str, Any]:
    spec = McpServerSpec(name, entry["command"], tuple(entry["args"]), tuple(entry["env"].items()))
    try:
        session = McpSession(spec, startup_timeout=FIRST_START_SECONDS)
    except McpError as error:
        raise ChoiceError(f"It would not start: {error}") from error
    try:
        tools = session.list_tools()
    except McpError as error:
        raise ChoiceError(f"It started but did not answer: {error}") from error
    finally:
        session.close()
    offered = next((item for item in tools if item.get("name") == tool), None)
    if offered is None:
        raise ChoiceError(f"It does not offer the {tool} tool any more.")
    return offered


def use(server: "AssistantServer", role_name: str, choice_id: str, inputs: dict[str, str]) -> dict[str, Any]:
    if role_name not in settings_store.ROLE_NAMES:
        return {"ok": False, "error": f"unknown job '{role_name}'"}
    try:
        kind = choice_id.split(":", 1)[0]
        if kind == "builtin":
            wanted, entry, role = _builtin(choice_id.split(":", 1)[1])
        elif kind == "found":
            wanted, entry, role = _found(role_name, choice_id)
        elif kind == "suggested":
            wanted, entry, role = _suggested(choice_id, inputs)
        else:
            raise ChoiceError("That choice is not offered any more.")
        offered = _first_start(wanted, entry, role["tool"])
    except ChoiceError as error:
        return {"ok": False, "error": str(error)}
    if not role["arguments"] and (limit := find_limit_argument(offered)):
        role["arguments"] = {limit: search_choices.RESULT_LIMIT}
    previous = server.settings
    name = _free_name(wanted, entry, previous["tool_servers"])
    updated = {**previous, "tool_servers": {**previous["tool_servers"], name: entry},
               "roles": {**previous["roles"], role_name: {"server": name, **role}}}
    try:
        stored = server.replace_settings(updated)
        result = call_role(server.mcp, stored, role_name, search_choices.TEST_QUERIES[role_name], TEST_SECONDS)
        if result.is_error:
            raise McpError(result.text.strip() or "the test search failed")
    except (settings_store.SettingsError, McpError) as error:
        server.replace_settings(previous)
        return {"ok": False, "error": f"The test search did not work, so nothing was changed: {error}"}
    return {"ok": True, "server": name, "message": "It works."}
