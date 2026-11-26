"""The assistant's self-check: is everything it depends on working, and what to do if not.

``run_checks(server)`` returns a list of ``{"name", "ok", "detail", "fix"}``
for ``GET /check`` (the Search & Tools page's "Check everything" button and
``happy-bot doctor``). Each check is quick and read-only:

- the active model answers its model list (or is reachable at all);
- each enabled tool server starts and lists its tools;
- the file-search and web-search roles point at tools that exist;
- keyboard control has the desktop's consent saved (the portal restore
  token), so typing into other apps will not ask again;
- the installed panel applet's version matches the daemon's;
- routines' systemd units match the settings, and the daemon has no
  recorded error;
- offline Wikipedia, when it is set up, still has its archive, and its last
  background download did not fail (``_wikipedia``);
- the helper programs the most-used tools rely on are installed.

``fix`` is a plain sentence the user can act on, never a log path. A check
that cannot run reports itself as failed with the reason; nothing here
changes anything.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__, input_portal, settings as settings_store, user_timers
from .mcp_client import McpError
from .providers import ProviderError
from .providers.openai_compatible import list_models
from .routines import desired_units

if TYPE_CHECKING:
    from .daemon_http import AssistantServer

APPLET_ID = "io.github.dragonswithin.happybot"
HELPERS = {"gio": "opening files and the trash", "qdbus6": "the clipboard and KDE settings",
           "wpctl": "sound", "nmcli": "networking", "kreadconfig6": "reading KDE settings",
           "notify-send": "notifications and reminders", "tesseract": "reading text in pictures",
           "spectacle": "screenshots", "pactl": "sound devices", "kdeconnect-cli": "the phone",
           "pw-record": "talking to Happy Bot (the microphone)"}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _model(settings: dict[str, Any]) -> dict[str, Any]:
    model = settings_store.active_model(settings)
    if model is None:
        return _check("AI model", False, "No model is chosen.", "Choose or add one on the AI Model page.")
    try:
        offered = list_models(model["base_url"], model.get("api_key", ""), headers=model.get("headers"))
    except ProviderError as error:
        return _check("AI model", False, f"{model['model']} at {model['base_url']} did not answer: {error}",
                      "Start the model service, or check its address and key on the AI Model page.")
    listed = any(item["id"] == model["model"] for item in offered)
    return _check("AI model", True, f"{model['model']} answers" + ("" if listed or not offered else
                  " (the service does not list it, which some services do not)"))


def _tool_servers(server: "AssistantServer") -> list[dict[str, Any]]:
    results = []
    for name, entry in sorted(server.settings["tool_servers"].items()):
        if not entry["enabled"]:
            continue
        try:
            count = len(server.mcp.list_tools(name))
            results.append(_check(f"Tool server {name}", True, f"{count} tools"))
        except McpError as error:
            results.append(_check(f"Tool server {name}", False, str(error),
                                  "Check its start command and environment under Search & Tools, or switch it off."))
    return results


def _roles(server: "AssistantServer") -> list[dict[str, Any]]:
    results = []
    for role, label, row in (("file_search", "File search", "Files"), ("web_search", "Web search", "Web")):
        config = server.settings["roles"].get(role)
        if not config:
            results.append(_check(label, False, "Not set up.",
                                  f"On the Search & Tools page, press Set up next to {row}."))
            continue
        try:
            names = [tool["name"] for tool in server.mcp.list_tools(config["server"])]
        except McpError as error:
            results.append(_check(label, False, str(error), "Fix its tool server under Search & Tools."))
            continue
        ok = config["tool"] in names
        results.append(_check(label, ok, f"{config['tool']} from {config['server']}" if ok else
                              f"{config['server']} no longer offers {config['tool']}", "Choose its tool again."))
    return results


def _applet_version() -> str:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    try:
        return json.loads((data_home / "plasma/plasmoids" / APPLET_ID / "metadata.json").read_text())["KPlugin"]["Version"]
    except (OSError, ValueError, KeyError):
        return ""


def _routines(server: "AssistantServer") -> dict[str, Any]:
    wanted = set(desired_units(server.settings.get("routines", {})))
    present = set(user_timers.owned_units(server.unit_dir, "routine"))
    if wanted == present:
        return _check("Routines", True, f"{len(wanted)} scheduled or watching")
    return _check("Routines", False, f"{len(wanted - present)} missing, {len(present - wanted)} left over",
                  "Open the Routines page and save any routine again, or restart the assistant.")


def _wikipedia(server: "AssistantServer") -> list[dict[str, Any]]:
    from . import wikipedia_library

    wikipedia = server.settings.get("wikipedia") or {}
    download = server.wikipedia_download.progress.snapshot()
    results = []
    if wikipedia.get("server"):
        found = wikipedia_library.archives(wikipedia.get("folder") or "")
        results.append(_check("Offline Wikipedia", bool(found),
                              f"{Path(found[0].path).name} in {wikipedia['folder']}" if found
                              else f"no archive in {wikipedia.get('folder')}",
                              "On the Search & Tools page, press Set up… next to Wikipedia and choose it again."))
    if download["state"] == "failed":
        results.append(_check("Offline Wikipedia download", False, download["message"],
                              "On the Search & Tools page, press Set up… next to Wikipedia to try again; "
                              "it carries on from where it stopped."))
    return results


def run_checks(server: "AssistantServer") -> list[dict[str, Any]]:
    """Every check, in the order a user would fix them (see module docstring)."""
    results = [_model(server.settings), *_tool_servers(server), *_roles(server)]
    allowed = input_portal.consent_saved()
    results.append(_check("Typing into other apps", allowed,
                          "Allowed." if allowed else "Not allowed yet.",
                          "On the Behaviour page, press Allow next to Typing into other apps, then choose "
                          "Allow when Plasma asks."))
    applet = _applet_version()
    results.append(_check("Panel applet", applet == __version__,
                          f"applet {applet or 'not installed'}, assistant {__version__}",
                          "Run the installer again, then restart the panel (log out and in)."))
    results.append(_routines(server))
    results.extend(_wikipedia(server))
    missing = [f"{program} ({purpose})" for program, purpose in HELPERS.items() if not shutil.which(program)]
    results.append(_check("Helper programs", not missing, "all installed" if not missing else "missing: " + ", ".join(missing),
                          "Install the missing programs with the system's package manager."))
    error = server.state.last_error
    results.append(_check("Background service", not error, error or "no errors recorded",
                          "Restart the assistant; if it happens again, the message above says what failed."))
    return results
