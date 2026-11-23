"""The assistant's one configuration file: schema, validation and storage.

Everything the user configures lives in
``$XDG_CONFIG_HOME/kde-ai-assistant/config.json`` (default
``~/.config/kde-ai-assistant/config.json``), written 0600 because tool-server
environment values may be secrets. The file is only ever written by
``save_settings`` after ``validate_settings`` accepted it; the daemon is the
only writer, and the settings page and CLI change it through the daemon.

Schema (version 1)::

    {
      "version": 1,
      "tool_servers": {
        "<name>": {
          "command": "/path/to/executable",   # required
          "args": ["..."],                    # default []
          "env": {"NAME": "value"},           # default {}, added to the daemon's environment
          "enabled": true,                    # default true; false keeps the entry but never starts it
          "read_only": false,                 # default false; true = the user vouches no tool changes anything
          "tools": null                       # default null = every tool; or a list of tool names to allow
        }
      },
      "models": {
        "<name>": {
          "provider": "openai_compatible",    # required; the only kind so far
          "base_url": "http://host:port/v1",  # required; the API root above /chat/completions
          "model": "<model id>",              # required; as the service names it
          "api_key": "",                      # default ""; sent as a bearer token when set
          "headers": {"Name": "value"},       # default {}; extra request headers some services need
          "context_window": 32768,            # default 32768; tokens, used to trim long conversations
          "vision": false                     # default false; whether the model accepts images
        }
      },
      "active_model": "<name>",               # default ""; which model answers requests
      "folders": {"Documents": "/path"},      # default {}; overrides for the user's standard folders.
                                              #   Names: Desktop, Documents, Downloads, Pictures, Music,
                                              #   Videos. A folder not listed here is wherever the system
                                              #   has it (XDG user-dirs, which KDE's Locations page sets).
      "approval_policy": "danger",            # default "danger"; which tool calls wait for the user:
                                              #   "danger"     only deletion and OS-level changes
                                              #   "changes"    anything that changes state
                                              #   "everything" every call, including reads
      "roles": {
        "file_search": {                      # optional; the tool the search bar queries while typing
          "server": "<name>", "tool": "<tool name>",
          "query_argument": "query",          # argument that receives the user's text
          "arguments": {"limit": 8}           # fixed extra arguments, default {}
        },
        "web_search": { ...same shape... }    # optional; preferred tool for questions about the web
      }
    }

Server names are 1 to 64 characters of letters, digits, ``_``, ``.`` or
``-``; model names follow the same rule. A role must point at a configured
server and ``active_model`` at a configured model. Unknown keys are rejected
so a typo is reported instead of silently ignored.

``redacted`` is the form sent to clients: tool-server environment values,
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

from .mcp_client import McpServerSpec
from .runtime_paths import APP_DIR_NAME, write_private_file

SETTINGS_VERSION = 1
PROVIDER_KINDS = ("openai_compatible",)
DEFAULT_CONTEXT_WINDOW = 32768
APPROVAL_POLICIES = ("danger", "changes", "everything")
FOLDER_NAMES = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
ROLE_NAMES = ("file_search", "web_search")
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class SettingsError(ValueError):
    """The settings are not valid; the message says which part and why."""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def default_settings() -> dict[str, Any]:
    return {
        "version": SETTINGS_VERSION, "tool_servers": {}, "roles": {}, "models": {}, "active_model": "",
        "approval_policy": "danger", "folders": {},
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


def _validate_server(name: str, raw: Any) -> dict[str, Any]:
    where = f"tool server '{name}'"
    _require(bool(_NAME_PATTERN.match(name)), f"{where}: names use letters, digits, '_', '.' or '-' (max 64)")
    _require(isinstance(raw, dict), f"{where} must be an object")
    unknown = set(raw) - {"command", "args", "env", "enabled", "read_only", "tools"}
    _reject_unknown(unknown, f"{where}: ")
    command = raw.get("command")
    _require(isinstance(command, str) and bool(command.strip()), f"{where}: 'command' is required")
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
    _reject_unknown(set(raw) - {"provider", "base_url", "model", "api_key", "headers", "context_window", "vision"}, f"{where}: ")
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
    return {
        "provider": raw["provider"],
        "base_url": base_url.rstrip("/"),
        "model": raw["model"].strip(),
        "api_key": api_key.strip(),
        "headers": {key.strip(): value for key, value in headers.items()},
        "context_window": window,
        "vision": raw.get("vision", False),
    }


def validate_settings(raw: Any) -> dict[str, Any]:
    """Return a normalised copy of ``raw`` with defaults filled in, or raise ``SettingsError``."""
    _require(isinstance(raw, dict), "settings must be an object")
    _reject_unknown(set(raw) - {"version", "tool_servers", "roles", "models", "active_model", "approval_policy", "folders"}, "")
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
    models = {name: _validate_model(name, value) for name, value in raw_models.items()}
    _require(isinstance(active_model, str), "'active_model' must be a model name")
    _require(not active_model or active_model in models, f"'active_model': model '{active_model}' is not set up")
    folders = raw.get("folders", {})
    _require(isinstance(folders, dict), "'folders' must be an object")
    for name, path in folders.items():
        _require(name in FOLDER_NAMES, f"'folders': unknown folder '{name}' (known: {', '.join(FOLDER_NAMES)})")
        _require(
            isinstance(path, str) and path.startswith(("/", "~")),
            f"'folders': {name} must be an absolute path or start with ~",
        )
    policy = raw.get("approval_policy", "danger")
    _require(policy in APPROVAL_POLICIES, f"'approval_policy' must be one of {', '.join(APPROVAL_POLICIES)}")
    return {
        "version": SETTINGS_VERSION,
        "tool_servers": servers,
        "roles": roles,
        "models": models,
        "active_model": active_model,
        "approval_policy": policy,
        "folders": {name: os.path.expanduser(path) for name, path in folders.items()},
    }


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
        if not isinstance(server, dict) or not isinstance(server.get("env"), dict):
            continue
        previous = stored.get("tool_servers", {}).get(name, {}).get("env", {})
        kept = {}
        for key, value in server["env"].items():
            if value is None:
                if key in previous:
                    kept[key] = previous[key]
            else:
                kept[key] = value
        server["env"] = kept
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
        )
        for name, server in sorted(settings["tool_servers"].items())
        if server["enabled"]
    ]
