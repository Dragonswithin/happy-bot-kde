"""Software tools: one search across every source, update history, Flatpak permissions, firmware.

Installing, updating and removing software stays with ``run_in_terminal``
(``tools/shell.py``), where the user sees it and types their password, and
under the install rules in the user's instructions. These tools give the
model what it needs to choose well and report accurately:

- ``search_software`` asks the distribution's repositories (``pacman -Ss``),
  the AUR (``yay -Ss --aur``, when yay is installed) and every Flatpak remote
  (``flatpak search``) at once, and labels each hit with its source, so the
  model never misses the AUR or a project's own Flatpak remote again.
- ``recent_updates`` reads ``/var/log/pacman.log`` for the last upgrade
  transactions: what was installed, upgraded or removed, and when.
- ``flatpak_permissions`` shows an app's sandbox permissions, and
  ``set_flatpak_permission`` changes one for this user only (``flatpak
  override --user``); ``--reset`` puts the app's defaults back.
- ``firmware_updates`` lists available firmware updates (``fwupdmgr``).

Everything is ``read`` except changing a Flatpak permission (``change``).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from ..desktop_context import run_command
from .power import run_checked
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

PACMAN_LOG = Path("/var/log/pacman.log")
MAX_HITS = 15
_ACTIONS = re.compile(r"^\[([^\]]+)\] \[ALPM\] (installed|upgraded|removed|downgraded) (\S+) \((.*)\)$")


def _optional(command: list[str], timeout: float = 60) -> str:
    if not shutil.which(command[0]):
        return ""
    result = run_command(command, timeout=timeout)
    return result["stdout"] if result["ok"] else ""


def search_software(arguments: dict[str, Any]) -> str:
    query = str(arguments.get("query") or "").strip()
    if not query or not re.fullmatch(r"[\w .+-]{2,60}", query):
        raise ToolFailure("'query' must be a short name to search for")
    sections = []
    repo = re.findall(r"^(\S+)/(\S+) (\S+).*\n\s+(.*)$", _optional(["pacman", "-Ss", query]), re.M)
    sections.append("Distribution repositories:\n" + ("\n".join(
        f"  {name} {version} [{repository}] - {description[:100]}" for repository, name, version, description in repo[:MAX_HITS])
        or "  none"))
    if shutil.which("yay"):
        aur = re.findall(r"^aur/(\S+) (\S+).*\n\s+(.*)$", _optional(["yay", "-Ss", "--aur", query], timeout=90), re.M)
        sections.append("AUR (community; prefer names ending in -bin for pre-built):\n" + ("\n".join(
            f"  {name} {version} - {description[:100]}" for name, version, description in aur[:MAX_HITS]) or "  none"))
    flatpaks = _optional(["flatpak", "search", "--columns=name,application,remotes", query])
    rows = [line.split("\t") for line in flatpaks.splitlines() if "\t" in line]
    sections.append("Flatpak (all configured remotes):\n" + ("\n".join(
        f"  {row[0]} [{row[1]}] from {row[2]}" for row in rows[:MAX_HITS] if len(row) >= 3) or "  none"))
    return "\n".join(sections)


def recent_updates(arguments: dict[str, Any]) -> str:
    try:
        lines = PACMAN_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-20000:]
    except OSError as error:
        raise ToolFailure(f"the package log could not be read: {error}") from error
    wanted = str(arguments.get("package") or "").lower()
    changes = []
    for line in lines:
        match = _ACTIONS.match(line)
        if match and (not wanted or wanted in match.group(3).lower()):
            changes.append(match.groups())
    if not changes:
        return "No package changes are recorded" + (f" for {wanted}." if wanted else ".")
    last_day = changes[-1][0][:10]
    shown = [change for change in changes if change[0].startswith(last_day)] if not wanted else changes[-40:]
    counts: dict[str, int] = {}
    for change in shown:
        counts[change[1]] = counts.get(change[1], 0) + 1
    summary = ", ".join(f"{count} {action}" for action, count in counts.items())
    body = "\n".join(f"{time[:16]}  {action:<10} {name} ({detail})" for time, action, name, detail in shown[-80:])
    kernel = [change for change in shown if re.match(r"linux(-[a-z]+)?$", change[2])]
    note = "\nThe kernel was updated: a reboot is needed to use it." if kernel else ""
    return f"{'Changes to ' + wanted if wanted else 'Latest update day ' + last_day}: {summary}\n{body}{note}"


def flatpak_permissions(arguments: dict[str, Any]) -> str:
    app = str(arguments.get("app") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,120}", app):
        raise ToolFailure("'app' must be a Flatpak application id such as org.mozilla.firefox")
    return run_checked(["flatpak", "info", "--show-permissions", app]) or "No special permissions."


_PERMISSION = re.compile(r"^(--(?:no)?filesystem=[^\s;]+|--(?:un)?share=(?:network|ipc)|--(?:no)?socket=[a-z-]+"
                         r"|--(?:no)?device=[a-z]+|--reset)$")


def set_flatpak_permission(arguments: dict[str, Any]) -> str:
    app = str(arguments.get("app") or "").strip()
    permission = str(arguments.get("permission") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,120}", app):
        raise ToolFailure("'app' must be a Flatpak application id")
    if not _PERMISSION.match(permission):
        raise ToolFailure("'permission' must be one flatpak override option such as --filesystem=~/Music, "
                          "--nofilesystem=home, --unshare=network, --socket=wayland, --device=dri or --reset")
    run_checked(["flatpak", "override", "--user", permission, app])
    return f"Applied {permission} to {app} for this user. Restart the app for it to take effect."


def firmware_updates(arguments: dict[str, Any]) -> str:
    output = _optional(["fwupdmgr", "get-updates", "--json"], timeout=120)
    try:
        devices = json.loads(output or "{}").get("Devices", [])
    except ValueError:
        devices = []
    if not devices:
        return "No firmware updates are available (or fwupd is not installed)."
    return "\n".join(f"{device.get('Name')}: {', '.join(release.get('Version', '?') for release in device.get('Releases', []))}"
                     for device in devices) + "\nInstall them with fwupdmgr update in a terminal."


def software_tools() -> list[Tool]:
    return [
        Tool("search_software", "Search for software in every source at once: the distribution's repositories, "
             "the AUR and Flatpak remotes, each result labelled with where it comes from. Use before installing.",
             object_schema({"query": {"type": "string"}}, ["query"]), RISK_READ, search_software,
             summarize=lambda a: f"Search for {a.get('query', '?')} in every software source"),
        Tool("recent_updates", "What the last system update installed, upgraded or removed (or the history of one "
             "package), and whether a reboot is needed.", object_schema({"package": {"type": "string"}}),
             RISK_READ, recent_updates, summarize=lambda a: "Check the update history"),
        Tool("flatpak_permissions", "A Flatpak app's sandbox permissions (files, network, devices).",
             object_schema({"app": {"type": "string"}}, ["app"]), RISK_READ, flatpak_permissions,
             summarize=lambda a: f"Check what {a.get('app', '?')} may access"),
        Tool("set_flatpak_permission", "Grant or remove one Flatpak permission for an app, for this user only "
             "(--reset restores its defaults).",
             object_schema({"app": {"type": "string"}, "permission": {"type": "string"}}, ["app", "permission"]),
             RISK_CHANGE, set_flatpak_permission,
             summarize=lambda a: f"Flatpak {a.get('app', '?')}: {a.get('permission', '?')}"),
        Tool("firmware_updates", "Firmware updates available for this computer's devices.", object_schema(),
             RISK_READ, firmware_updates, summarize=lambda a: "Check for firmware updates"),
    ]
