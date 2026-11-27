"""The assistant's one configuration file: schema, validation and storage.

Everything the user configures lives in
``$XDG_CONFIG_HOME/happy-bot/config.json`` (default
``~/.config/happy-bot/config.json``), written 0600 because tool-server
environment values may be secrets. The file is only ever written by
``save_settings`` after ``validate_settings`` accepted it; the daemon is the
only writer, and the settings page and CLI change it through the daemon.

Schema (version 1)::

    {
      "version": 1,
      "tool_servers": {
        "<name>": {
          "command": "/path/to/executable",   # required unless "url" is given: a program to start
          "url": "",                          #   or, instead, the address of an HTTP MCP server (mcp_http.py)
          "headers": {"Name": "value"},       # default {}; HTTP headers for a url server (secret, like env)
          "args": ["..."],                    # default []
          "env": {"NAME": "value"},           # default {}, added to the daemon's environment
          "enabled": true,                    # default true; false keeps the entry but never starts it
          "read_only": false,                 # default false; true = the user vouches no tool changes anything
          "tools": null                       # default null = every tool; or a list of tool names to allow
        }
      },
      "models": {
        "<name>": {
          "provider": "openai_compatible",    # required; or "openai_responses" (OpenAI's newer API, which its
                                              #   newest models need for tools; the OpenAI preset sets it)
          "base_url": "http://host:port/v1",  # required; the API root above /chat/completions
          "model": "<model id>",              # required; as the service names it
          "api_key": "",                      # default ""; sent as a bearer token when set
          "headers": {"Name": "value"},       # default {}; extra request headers some services need
          "context_window": 32768,            # default 32768; tokens, used to trim long conversations
          "vision": false,                    # default false; whether the model accepts images
          "input_price": 0,                   # default 0; cost per million input tokens, in the user's
          "output_price": 0,                  #   currency, for spending totals and the limit (spend.py)
          "monthly_cap": 0,                   # default 0 = no limit; once this model has cost this much this
                                              #   month, requests skip it and go to the next model in the order
          "hand_over_long": false             # default false; true: when a request needs more than
                                              #   ask_stream.HAND_OVER_STEPS steps, the next model in the order
                                              #   finishes it (a quick model first, a strong one after it)
        }
      },
      "model_order": ["<name>", ...],         # default: every model; the order they are asked in. The first
                                              #   answers; when it fails (or hands a long request over) the next
                                              #   one does. Models left out are added at the end.
      "active_model": "<name>",               # always the first of model_order (kept for the CLI and older
                                              #   clients); setting it moves that model to the front
      "folders": {"Documents": "/path"},      # default {}; overrides for the user's standard folders.
                                              #   Names: Desktop, Documents, Downloads, Pictures, Music,
                                              #   Videos. A folder not listed here is wherever the system
                                              #   has it (XDG user-dirs, which KDE's Locations page sets).
      "history_days": 30,                     # default 30; days a conversation is kept after its last
                                              #   use, in ~/.local/share/happy-bot/conversations.
                                              #   0 keeps nothing on disk. Range 0 to 3650.
      "approval_policy": "danger",            # default "danger"; which tool calls wait for the user:
                                              #   "danger"     only deletion and OS-level changes
                                              #   "changes"    anything that changes state
                                              #   "everything" every call, including reads
      "agent": {                              # how a request is carried out; every key optional
        "instructions": "...",                # default SUGGESTED_INSTRUCTIONS; the user's own standing
                                              #   instructions, added to the model's instructions for new
                                              #   conversations. "" means none. At most 4000 characters.
        "max_steps": 40,                      # default 40; model requests one request may make before
                                              #   it stops with "step_limit". Range 5 to 200.
        "notify_after_seconds": 60,           # default 60; a request that took longer ends with a
                                              #   desktop notification. 0 never notifies. Range 0 to 3600.
        "command_timeout_seconds": 60,        # default 60; how long run_command lets a command run
                                              #   when the model names no limit. Range 5 to 1800.
        "terminal": "",                       # default "" = KDE's default terminal (System Settings,
                                              #   Default Applications), else Konsole; or one of
                                              #   SUPPORTED_TERMINALS in tools/shell.py
        "load_plugins": false,                # default false; true: load tools from the user's plugin files in
                                              #   ~/.config/happy-bot/plugins (tools/plugins.py)
        "serve_tools": false,                 # default false; true: other AI programs on this computer may use
                                              #   the built-in tools through `happy-bot mcp-serve`;
                                              #   anything needing approval is refused there
        "local_only": false,                  # default false; true: nothing read leaves the computer: a hosted
                                              #   model is refused, and web search and web pages are not offered
        "app_context": "local",               # default "local"; who may see what Happy Bot reads from the
                                              #   application the user is in (its name, title, version, and
                                              #   for a "Help with …" chat its selection, controls and open
                                              #   file; also what tools read inside windows): "off" (no AI is
                                              #   told about it), "local" (AIs on this computer only), "any"
                                              #   (online AIs too). See app_context.py.
        "confirm_plans": false,               # default false; true: before a request that changes more than
                                              #   one thing, the assistant first shows its plan and waits for
                                              #   the user to agree.
        "disabled_tool_groups": []            # default []; built-in action groups never offered to the
                                              #   model: "windows", "apps", "gui", "system", "files",
                                              #   "shell", "phone", "schedule" (see tools/catalog.py).
                                              #   Reading the desktop
                                              #   and the user's tool servers are not affected.
      },
      "ui": {...},                            # the panel widget's and the app's look and feel, kept once
                                              #   for both; keys, defaults and ranges: ui_settings.py
      "voice": {...},                         # talking to Happy Bot: the microphone button and the speech-
                                              #   to-text service; keys and defaults: voice.py
      "wikipedia": {...},                     # offline Wikipedia: its reader tool server, the archives'
                                              #   folder and monthly updating; keys: wikipedia_library.py
      "personal": {                           # where the assistant keeps the user's notes and to-dos
        "notes_file": "",                     #   default "" = Notes.md in the Documents folder
        "todo_file": ""                       #   default "" = To-do.md in the Documents folder
      },                                      #   (absolute paths or ~; plain Markdown, see tools/notes.py)
      "layouts": {                            # default {}; saved window layouts, name -> list of
        "<name>": [{"app": "org.kde.kate",    #   {app, x, y, width, height} in pixels; schema in
                    "x": 0, "y": 0,           #   tools/workspace.py (validate_layouts)
                    "width": 960, "height": 1080}]
      },
      "routines": {                           # default {}; named requests the user saved, run when asked,
        "<name>": {...}                       #   on a schedule or when a folder changes. Schema and meaning:
      },                                      #   routines.py
      "roles": {
        "file_search": {                      # optional; the tool the search bar queries while typing
          "server": "<name>", "tool": "<tool name>",
          "query_argument": "query",          # argument that receives the user's text
          "arguments": {"limit": 8}           # fixed extra arguments, default {}
        },
        "web_search": { ...same shape... }    # optional; preferred tool for questions about the web
      }
    }

The settings page (the applet's "Configure…" dialog) has a control for every
key above, so a user never edits this file; the ``happy-bot`` CLI
covers the main ones (models, tool servers, roles, policy, folders) for
scripts.

Server names are 1 to 64 characters of letters, digits, ``_``, ``.`` or
``-``; model names follow the same rule. A role must point at a configured
server and ``model_order`` at configured models. Unknown keys are rejected
so a typo is reported instead of silently ignored, with one exception:
settings from before the model order (``agent.fallback_model``,
``agent.quick_model``, ``agent.monthly_spend_cap``) are converted once
(``_model_order``): the quick model first with ``hand_over_long``, then the
active one, then the fallback, and the old total cap becomes each priced
model's ``monthly_cap``.

``redacted`` is the form sent to clients: tool-server environment and header values,
model header values and non-empty model API keys are replaced by ``None``. ``merge_redacted`` is its
inverse on update: a ``None`` value means "keep what is stored", so a client
can round-trip settings without ever holding a secret.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from .agent_loop import MAX_STEPS
from . import remembered_facts
from .ui_settings import UiSettingsError, validate_ui
from .voice import VoiceSettingsError, validate_voice
from .wikipedia_library import WikipediaError, validate_wikipedia
from .mcp_client import McpServerSpec
from .routines import RoutineError, validate_routines
from .tools.workspace import LayoutError, validate_layouts
from .runtime_paths import APP_DIR_NAME, write_private_file
from .tools.shell import DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, SUPPORTED_TERMINALS

SETTINGS_VERSION = 1
PROVIDER_KINDS = ("openai_compatible", "openai_responses")  # see providers/__init__.py
DEFAULT_CONTEXT_WINDOW = 32768
APPROVAL_POLICIES = ("danger", "changes", "everything")
FOLDER_NAMES = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
DEFAULT_HISTORY_DAYS = 30
ROLE_NAMES = ("file_search", "web_search")
# Built-in action groups the user can switch off; tools/catalog.py builds one
# list of tools per name (a test keeps the two in step).
TOOL_GROUPS = ("windows", "apps", "gui", "system", "files", "shell", "phone", "schedule")
MAX_INSTRUCTIONS_CHARS = 4000
DEFAULT_NOTIFY_AFTER_SECONDS = 60
# The starting text of the user's instructions: preferences, not rules the
# assistant needs to work, so they are shown and editable on the settings page
# (Behaviour, "Restore suggested") instead of hidden in the system prompt.
SUGGESTED_INSTRUCTIONS = (
    "When installing software, use official sources: the distribution's own packages first, then the project's "
    "official pre-built packages (for example its Flatpak). Build from source only when nothing pre-built exists "
    "or I ask.\n"
    "Never install from a third-party build, an unofficial repository or a downloaded install script without asking "
    "me first: say who publishes it and why the official sources did not work, then wait for my answer.\n"
    "Never stop or kill a program you started for me unless I ask."
)
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class SettingsError(ValueError):
    """The settings are not valid; the message says which part and why."""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


# Who may see what is read from the user's applications (app_context.py owns the meaning).
APP_CONTEXT_POLICIES = ("off", "local", "any")
APP_CONTEXT_DEFAULT = "local"


def config_path() -> Path:
    return config_dir() / "config.json"


def default_agent() -> dict[str, Any]:
    return {
        "instructions": SUGGESTED_INSTRUCTIONS, "remembered_facts": [], "max_steps": MAX_STEPS, "notify_after_seconds": DEFAULT_NOTIFY_AFTER_SECONDS,
        "command_timeout_seconds": DEFAULT_TIMEOUT_SECONDS, "terminal": "", "disabled_tool_groups": [],
        "confirm_plans": False, "local_only": False, "app_context": APP_CONTEXT_DEFAULT,
        "load_plugins": False, "serve_tools": False,
    }


def default_settings() -> dict[str, Any]:
    return {
        "version": SETTINGS_VERSION, "tool_servers": {}, "roles": {}, "models": {}, "active_model": "",
        "approval_policy": "danger", "folders": {}, "history_days": DEFAULT_HISTORY_DAYS, "agent": default_agent(),
        "routines": {}, "layouts": {}, "personal": {"notes_file": "", "todo_file": ""},
        "ui": validate_ui({}), "voice": validate_voice({}), "wikipedia": validate_wikipedia({}),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SettingsError(message)


def _reject_unknown(unknown: set[str], where: str) -> None:
    if unknown:
        raise SettingsError(f"{where}unknown setting {sorted(unknown)[0]!r}")


def _string_list(value: Any, where: str) -> list[str]:
    _require(isinstance(value, list) and all(isinstance(item, str) for item in value), f"{where} must be a list of strings")
    return list(value)


def _whole_number(value: Any, low: int, high: int, message: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool) and low <= value <= high, message)
    return value


def _validate_agent(raw: Any) -> dict[str, Any]:
    _require(isinstance(raw, dict), "'agent' must be an object")
    defaults = default_agent()
    _reject_unknown(set(raw) - set(defaults), "'agent': ")
    merged = {**defaults, **raw}
    instructions = merged["instructions"]
    _require(isinstance(instructions, str), "'agent': 'instructions' must be text")
    _require(len(instructions) <= MAX_INSTRUCTIONS_CHARS,
             f"'agent': 'instructions' may be at most {MAX_INSTRUCTIONS_CHARS} characters")
    try:
        if "remembered_facts" not in raw:
            instructions, facts = remembered_facts.split_legacy(instructions.strip(), SUGGESTED_INSTRUCTIONS)
        else:
            facts = remembered_facts.validate(merged["remembered_facts"])
    except ValueError as error:
        raise SettingsError(str(error)) from error
    terminal = merged["terminal"]
    _require(terminal == "" or terminal in SUPPORTED_TERMINALS,
             f"'agent': 'terminal' must be empty (automatic) or one of {', '.join(SUPPORTED_TERMINALS)}")
    for flag in ("confirm_plans", "local_only", "load_plugins", "serve_tools"):
        _require(isinstance(merged[flag], bool), f"'agent': '{flag}' must be true or false")
    _require(merged["app_context"] in APP_CONTEXT_POLICIES,
             f"'agent': 'app_context' must be one of {', '.join(APP_CONTEXT_POLICIES)}")
    groups = _string_list(merged["disabled_tool_groups"], "'agent': 'disabled_tool_groups'")
    for group in groups:
        _require(group in TOOL_GROUPS, f"'agent': unknown tool group '{group}' (known: {', '.join(TOOL_GROUPS)})")
    return {
        "instructions": instructions.strip(),
        "remembered_facts": facts,
        "max_steps": _whole_number(merged["max_steps"], 5, 200, "'agent': 'max_steps' must be a whole number from 5 to 200"),
        "notify_after_seconds": _whole_number(
            merged["notify_after_seconds"], 0, 3600, "'agent': 'notify_after_seconds' must be a whole number from 0 to 3600"),
        "command_timeout_seconds": _whole_number(
            merged["command_timeout_seconds"], 5, MAX_TIMEOUT_SECONDS,
            f"'agent': 'command_timeout_seconds' must be a whole number from 5 to {MAX_TIMEOUT_SECONDS}"),
        "terminal": terminal,
        "disabled_tool_groups": sorted(set(groups)),
        "confirm_plans": merged["confirm_plans"],
        "local_only": merged["local_only"],
        "app_context": merged["app_context"],
        "load_plugins": merged["load_plugins"],
        "serve_tools": merged["serve_tools"],
    }


def _validate_server(name: str, raw: Any) -> dict[str, Any]:
    where = f"tool server '{name}'"
    _require(bool(_NAME_PATTERN.match(name)), f"{where}: names use letters, digits, '_', '.' or '-' (max 64)")
    _require(isinstance(raw, dict), f"{where} must be an object")
    unknown = set(raw) - {"command", "args", "env", "enabled", "read_only", "tools", "url", "headers"}
    _reject_unknown(unknown, f"{where}: ")
    command = raw.get("command", "")
    url = raw.get("url", "")
    _require(isinstance(url, str) and (not url or url.startswith(("http://", "https://"))),
             f"{where}: 'url' must start with http:// or https://")
    _require(isinstance(command, str) and (bool(command.strip()) != bool(url.strip())),
             f"{where}: 'command' is required (or give 'url' for an HTTP server, but not both)")
    headers = raw.get("headers", {})
    _require(isinstance(headers, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()),
             f"{where}: 'headers' must map header names to text values")
    env = raw.get("env", {})
    _require(
        isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()),
        f"{where}: 'env' must map names to text values",
    )
    tools = raw.get("tools")
    for flag in ("enabled", "read_only"):
        _require(isinstance(raw.get(flag, False), bool), f"{where}: '{flag}' must be true or false")
    return {
        "command": command.strip(),
        "url": url.strip(),
        "headers": dict(headers),
        "args": _string_list(raw.get("args", []), f"{where}: 'args'"),
        "env": dict(env),
        "enabled": raw.get("enabled", True),
        "read_only": raw.get("read_only", False),
        "tools": None if tools is None else _string_list(tools, f"{where}: 'tools'"),
    }


def _validate_role(role: str, raw: Any, servers: dict[str, Any]) -> dict[str, Any]:
    where = f"role '{role}'"
    _require(role in ROLE_NAMES, f"unknown role '{role}' (known: {', '.join(ROLE_NAMES)})")
    _require(isinstance(raw, dict), f"{where} must be an object")
    unknown = set(raw) - {"server", "tool", "query_argument", "arguments"}
    _reject_unknown(unknown, f"{where}: ")
    for key in ("server", "tool"):
        _require(isinstance(raw.get(key), str) and bool(raw[key]), f"{where}: '{key}' is required")
    _require(raw["server"] in servers, f"{where}: tool server '{raw['server']}' is not set up")
    query_argument = raw.get("query_argument", "query")
    _require(isinstance(query_argument, str) and bool(query_argument), f"{where}: 'query_argument' must be a name")
    arguments = raw.get("arguments", {})
    _require(isinstance(arguments, dict), f"{where}: 'arguments' must be an object")
    return {
        "server": raw["server"],
        "tool": raw["tool"],
        "query_argument": query_argument,
        "arguments": copy.deepcopy(arguments),
    }


def _validate_model(name: str, raw: Any) -> dict[str, Any]:
    where = f"model '{name}'"
    _require(bool(_NAME_PATTERN.match(name)), f"{where}: names use letters, digits, '_', '.' or '-' (max 64)")
    _require(isinstance(raw, dict), f"{where} must be an object")
    _reject_unknown(set(raw) - {"provider", "base_url", "model", "api_key", "headers", "context_window", "vision",
                                "input_price", "output_price", "monthly_cap", "hand_over_long"}, f"{where}: ")
    for price in ("input_price", "output_price"):
        value = raw.get(price, 0)
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10000,
                 f"{where}: '{price}' must be a number from 0 (per million tokens)")
    _require(raw.get("provider") in PROVIDER_KINDS, f"{where}: 'provider' must be one of {', '.join(PROVIDER_KINDS)}")
    base_url = raw.get("base_url")
    _require(
        isinstance(base_url, str) and base_url.startswith(("http://", "https://")),
        f"{where}: 'base_url' must start with http:// or https://",
    )
    _require(isinstance(raw.get("model"), str) and bool(raw["model"].strip()), f"{where}: 'model' is required")
    api_key = raw.get("api_key", "")
    _require(isinstance(api_key, str), f"{where}: 'api_key' must be text")
    headers = raw.get("headers", {})
    _require(
        isinstance(headers, dict)
        and all(isinstance(k, str) and k.strip() and isinstance(v, str) for k, v in headers.items()),
        f"{where}: 'headers' must map header names to text values",
    )
    window = raw.get("context_window", DEFAULT_CONTEXT_WINDOW)
    _require(
        isinstance(window, int) and not isinstance(window, bool) and 1024 <= window <= 10_000_000,
        f"{where}: 'context_window' must be a whole number of tokens, at least 1024",
    )
    _require(isinstance(raw.get("vision", False), bool), f"{where}: 'vision' must be true or false")
    _require(isinstance(raw.get("hand_over_long", False), bool), f"{where}: 'hand_over_long' must be true or false")
    cap = raw.get("monthly_cap", 0)
    _require(isinstance(cap, (int, float)) and not isinstance(cap, bool) and 0 <= cap <= 1_000_000,
             f"{where}: 'monthly_cap' must be a number, 0 for no limit")
    return {
        "provider": raw["provider"],
        "base_url": base_url.rstrip("/"),
        "model": raw["model"].strip(),
        "api_key": api_key.strip(),
        "headers": {key.strip(): value for key, value in headers.items()},
        "context_window": window,
        "vision": raw.get("vision", False),
        "input_price": raw.get("input_price", 0),
        "output_price": raw.get("output_price", 0),
        "monthly_cap": cap,
        "hand_over_long": raw.get("hand_over_long", False),
    }


def _model_order(raw_order: Any, active: str, models: dict[str, dict[str, Any]], legacy: dict[str, Any]) -> list[str]:
    """Every model once, in the user's order, ``active`` first when given; converts pre-order settings.

    ``models`` is changed in place only for the conversion: the old quick model gets ``hand_over_long``
    and the old total cap becomes each priced model's ``monthly_cap``.
    """
    if raw_order is None:
        quick, fallback = str(legacy.get("quick_model") or ""), str(legacy.get("fallback_model") or "")
        raw_order = [name for name in (quick, active, fallback) if name]
        if quick in models:
            models[quick]["hand_over_long"] = True
        cap = legacy.get("monthly_spend_cap") or 0
        for model in models.values():
            if cap and not model["monthly_cap"] and (model["input_price"] or model["output_price"]):
                model["monthly_cap"] = cap
    _require(isinstance(raw_order, list) and all(isinstance(name, str) for name in raw_order),
             "'model_order' must be a list of model names")
    # A model removed elsewhere (the CLI, an older page) simply leaves the order.
    order = list(dict.fromkeys([*(name for name in raw_order if name in models), *sorted(models)]))
    if active and order and order[0] != active:
        order.remove(active)
        order.insert(0, active)
    return order


def validate_settings(raw: Any) -> dict[str, Any]:
    """Return a normalised copy of ``raw`` with defaults filled in, or raise ``SettingsError``."""
    _require(isinstance(raw, dict), "settings must be an object")
    _reject_unknown(set(raw) - {"version", "tool_servers", "roles", "models", "model_order", "active_model",
                                "approval_policy", "folders",
                                "history_days", "agent", "routines", "layouts", "personal", "ui", "voice",
                                "wikipedia"}, "")
    _require(raw.get("version", SETTINGS_VERSION) == SETTINGS_VERSION, "unsupported settings version")
    raw_servers = raw.get("tool_servers", {})
    raw_roles = raw.get("roles", {})
    raw_models = raw.get("models", {})
    active_model = raw.get("active_model", "")
    _require(isinstance(raw_servers, dict), "'tool_servers' must be an object")
    _require(isinstance(raw_roles, dict), "'roles' must be an object")
    _require(isinstance(raw_models, dict), "'models' must be an object")
    servers = {name: _validate_server(name, value) for name, value in raw_servers.items()}
    roles = {role: _validate_role(role, value, servers) for role, value in raw_roles.items()}
    raw_agent = dict(raw.get("agent") or {}) if isinstance(raw.get("agent", {}), dict) else raw.get("agent")
    legacy = {key: raw_agent.pop(key) for key in ("fallback_model", "quick_model", "monthly_spend_cap")
              if isinstance(raw_agent, dict) and key in raw_agent}
    models = {name: _validate_model(name, value) for name, value in raw_models.items()}
    _require(isinstance(active_model, str), "'active_model' must be a model name")
    _require(not active_model or active_model in models, f"'active_model': model '{active_model}' is not set up")
    order = _model_order(raw.get("model_order"), active_model, models, legacy)
    folders = raw.get("folders", {})
    _require(isinstance(folders, dict), "'folders' must be an object")
    for name, path in folders.items():
        _require(name in FOLDER_NAMES, f"'folders': unknown folder '{name}' (known: {', '.join(FOLDER_NAMES)})")
        _require(
            isinstance(path, str) and path.startswith(("/", "~")),
            f"'folders': {name} must be an absolute path or start with ~",
        )
    history_days = _whole_number(raw.get("history_days", DEFAULT_HISTORY_DAYS), 0, 3650,
                                 "'history_days' must be a whole number of days from 0 to 3650")
    policy = raw.get("approval_policy", "danger")
    _require(policy in APPROVAL_POLICIES, f"'approval_policy' must be one of {', '.join(APPROVAL_POLICIES)}")
    return {
        "version": SETTINGS_VERSION,
        "tool_servers": servers,
        "roles": roles,
        "models": models,
        "model_order": order,
        "active_model": order[0] if order else "",
        "approval_policy": policy,
        "folders": {name: os.path.expanduser(path) for name, path in folders.items()},
        "history_days": history_days,
        "agent": _validate_agent(raw_agent),
        "routines": _validate_routines(raw.get("routines", {})),
        "layouts": _validate_layouts(raw.get("layouts", {})),
        "personal": _validate_personal(raw.get("personal", {})),
        "ui": _validate_ui_group(raw.get("ui", {})),
        "voice": _validate_voice_group(raw.get("voice", {})),
        "wikipedia": _validate_wikipedia_group(raw.get("wikipedia", {}), servers),
    }


def _validate_wikipedia_group(raw: Any, servers: dict[str, Any]) -> dict[str, Any]:
    try:
        wikipedia = validate_wikipedia(raw)
    except WikipediaError as error:
        raise SettingsError(str(error)) from error
    if wikipedia["server"] not in servers:  # its reader was removed on the Tools page: no longer set up
        wikipedia = {**wikipedia, "server": "", "auto_update": False}
    return wikipedia


def _validate_ui_group(raw: Any) -> dict[str, Any]:
    try:
        return validate_ui(raw)
    except UiSettingsError as error:
        raise SettingsError(str(error)) from error


def _validate_voice_group(raw: Any) -> dict[str, Any]:
    try:
        return validate_voice(raw)
    except VoiceSettingsError as error:
        raise SettingsError(str(error)) from error


def _validate_personal(raw: Any) -> dict[str, str]:
    _require(isinstance(raw, dict), "'personal' must be an object")
    _reject_unknown(set(raw) - {"notes_file", "todo_file"}, "'personal': ")
    cleaned = {}
    for key in ("notes_file", "todo_file"):
        value = raw.get(key, "")
        _require(isinstance(value, str) and (not value.strip() or value.strip().startswith(("/", "~"))),
                 f"'personal': '{key}' must be empty or an absolute path")
        cleaned[key] = os.path.expanduser(value.strip()) if value.strip() else ""
    return cleaned


def _validate_layouts(raw: Any) -> dict[str, Any]:
    try:
        return validate_layouts(raw)
    except LayoutError as error:
        raise SettingsError(str(error)) from error


def _validate_routines(raw: Any) -> dict[str, Any]:
    try:
        return validate_routines(raw)
    except RoutineError as error:
        raise SettingsError(str(error)) from error


def load_settings(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the file; a missing file yields the defaults."""
    target = path or config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_settings()
    except (OSError, ValueError) as exc:
        raise SettingsError(f"could not read {target}: {exc}") from exc
    return validate_settings(raw)


def save_settings(settings: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Validate, then atomically write the file 0600. Returns what was stored."""
    normalised = validate_settings(settings)
    target = path or config_path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_private_file(target, json.dumps(normalised, indent=2, ensure_ascii=False) + "\n")
    return normalised


def redacted(settings: dict[str, Any]) -> dict[str, Any]:
    """Copy for clients: environment values and non-empty API keys become ``None``."""
    view = copy.deepcopy(settings)
    for server in view.get("tool_servers", {}).values():
        server["env"] = {name: None for name in server.get("env", {})}
        server["headers"] = {name: None for name in server.get("headers", {})}
    for model in view.get("models", {}).values():
        if model.get("api_key"):
            model["api_key"] = None
        model["headers"] = {name: None for name in model.get("headers", {})}
    return view


def merge_redacted(incoming: Any, stored: dict[str, Any]) -> Any:
    """Fill ``None`` secrets in ``incoming`` from ``stored`` (see ``redacted``)."""
    if not isinstance(incoming, dict):
        return incoming
    merged = copy.deepcopy(incoming)
    servers = merged.get("tool_servers")
    for name, server in (servers.items() if isinstance(servers, dict) else ()):
        if not isinstance(server, dict):
            continue
        for field in ("env", "headers"):
            if not isinstance(server.get(field), dict):
                continue
            previous = stored.get("tool_servers", {}).get(name, {}).get(field, {})
            server[field] = {key: (previous[key] if value is None else value)
                             for key, value in server[field].items() if value is not None or key in previous}
    models = merged.get("models")
    for name, model in (models.items() if isinstance(models, dict) else ()):
        if not isinstance(model, dict):
            continue
        previous_model = stored.get("models", {}).get(name, {})
        if "api_key" in model and model["api_key"] is None:
            model["api_key"] = previous_model.get("api_key", "")
        if isinstance(model.get("headers"), dict):
            old_headers = previous_model.get("headers", {})
            model["headers"] = {
                key: (old_headers[key] if value is None else value)
                for key, value in model["headers"].items()
                if value is not None or key in old_headers
            }
    return merged


def active_model(settings: dict[str, Any]) -> dict[str, Any] | None:
    """The configured model that answers requests, or None if none is chosen."""
    return settings.get("models", {}).get(settings.get("active_model") or "")


def server_specs(settings: dict[str, Any]) -> list[McpServerSpec]:
    """Launch specifications for every enabled tool server."""
    return [
        McpServerSpec(
            name=name,
            command=server["command"],
            args=tuple(server["args"]),
            env=tuple(sorted(server["env"].items())),
            read_only=server["read_only"],
            url=server.get("url", ""),
            headers=tuple(sorted(server.get("headers", {}).items())),
        )
        for name, server in sorted(settings["tool_servers"].items())
        if server["enabled"]
    ]
