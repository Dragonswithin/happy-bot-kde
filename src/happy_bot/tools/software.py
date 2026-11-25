"""Software tools: one search across every source, waiting updates, update history, Flatpak permissions, firmware.

Installing, updating and removing software stays with ``run_in_terminal``
(``tools/shell.py``), where the user sees it and types their password, and
under the install rules in the user's instructions. These tools give the
model what it needs to choose well and report accurately:

- ``search_software`` asks the distribution's repositories (``pacman -Ss``),
  the AUR (``yay -Ss --aur``, when yay is installed) and every Flatpak remote
  (``flatpak search``) at once, and labels each hit with its source, so the
  model never misses the AUR or a project's own Flatpak remote again. Hits
  already installed are marked (pacman's and yay's own marks; ``flatpak
  list`` for Flatpaks) and named first, so the model does not offer to
  install what the user has. When Shelly (an Arch package manager covering
  all three sources) is installed, the result ends with its install
  commands (``SHELLY_INSTALLS``), so the model installs through the user's
  own package manager; ``shell_risk`` treats them like ``pacman -S``.
- ``check_updates`` lists what is waiting, without changing anything: the
  distribution's packages (``checkupdates``, which syncs a private copy of
  the package lists), the AUR (``yay -Qua``) and Flatpak apps (``flatpak
  remote-ls --updates``); says whether the kernel is among them (a restart
  will be needed) or a restart is already pending (``shell.pending_reboot``);
  and gives the one command that updates all of it, for ``run_in_terminal``.
  A source that could not be checked is named rather than counted as
  "nothing to update". Without these programs it points to Discover's
  Updates page instead.
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
    sections, installed = [], []
    # pacman and yay end an installed package's line with "[installed]" or "(Installed)"; the rest of
    # the line is captured so that mark is kept, and installed ones are also named up front.
    repo = re.findall(r"^(\S+)/(\S+) (\S+)(.*)\n\s+(.*)$", _optional(["pacman", "-Ss", query]), re.M)
    installed += [name for _, name, _, rest, _ in repo if _INSTALLED.search(rest)]
    sections.append("Distribution repositories:\n" + ("\n".join(
        f"  {name} {version} [{repository}]{_mark(rest)} - {description[:100]}"
        for repository, name, version, rest, description in repo[:MAX_HITS]) or "  none"))
    if shutil.which("yay"):
        aur = re.findall(r"^aur/(\S+) (\S+)(.*)\n\s+(.*)$", _optional(["yay", "-Ss", "--aur", query], timeout=90), re.M)
        installed += [name for name, _, rest, _ in aur if _INSTALLED.search(rest)]
        sections.append("AUR (community; prefer names ending in -bin for pre-built):\n" + ("\n".join(
            f"  {name} {version}{_mark(rest)} - {description[:100]}" for name, version, rest, description in aur[:MAX_HITS])
            or "  none"))
    flatpaks = _optional(["flatpak", "search", "--columns=name,application,remotes", query])
    rows = [line.split("\t") for line in flatpaks.splitlines() if "\t" in line]
    have = set(_optional(["flatpak", "list", "--app", "--columns=application"]).split()) if rows else set()
    installed += [row[1] for row in rows if len(row) >= 3 and row[1] in have]
    sections.append("Flatpak (all configured remotes):\n" + ("\n".join(
        f"  {row[0]} [{row[1]}] from {row[2]}{' [installed]' if row[1] in have else ''}"
        for row in rows[:MAX_HITS] if len(row) >= 3) or "  none"))
    if shutil.which("shelly"):
        sections.append(SHELLY_INSTALLS)
    if installed:
        sections.insert(0, "Already installed (start it or say so; do not offer to install it again): "
                        + ", ".join(dict.fromkeys(installed)))
    return "\n".join(sections)


SHELLY_INSTALLS = (
    "Install with Shelly, the user's package manager, through run_in_terminal: shelly install standard NAME "
    "(distribution repositories), shelly install aur NAME (AUR), shelly install flatpak APP_ID (Flatpak). "
    "Use and show these, not pacman, yay or flatpak commands.")
_INSTALLED = re.compile(r"[\[(]installed[^\])]*[\])]", re.I)


def _mark(rest: str) -> str:
    return " [installed]" if _INSTALLED.search(rest) else ""


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


UPDATE_LIST_LIMIT = 25
_KERNEL = re.compile(r"^linux(-[a-z]+)?$")


def _waiting(command: list[str], none_code: int | None, timeout: float) -> list[str] | None:
    """Lines listing updates, [] for none, or None when the source could not be checked."""
    if not shutil.which(command[0]):
        return []
    result = run_command(command, timeout=timeout)
    if result["ok"]:
        return [line.strip() for line in result["stdout"].splitlines() if line.strip()]
    return [] if none_code is not None and result["returncode"] == none_code and not result["stdout"].strip() else None


def check_updates(arguments: dict[str, Any]) -> str:
    from .shell import pending_reboot

    if not shutil.which("checkupdates") and not shutil.which("flatpak"):
        return ("This computer's updates are not checked here. Open Discover's Updates page with the command "
                "plasma-discover --mode update.")
    sources = {
        "distribution": _waiting(["checkupdates"], 2, 180),
        "AUR": _waiting(["yay", "-Qua"], 1, 180),
        "Flatpak": _waiting(["flatpak", "remote-ls", "--updates", "--columns=application,version"], None, 120),
    }
    failed = [name for name, lines in sources.items() if lines is None]
    found = {name: lines for name, lines in sources.items() if lines}
    total = sum(len(lines) for lines in found.values())
    report = [f"{total} update{'s' if total != 1 else ''} waiting" + (
        ": " + ", ".join(f"{len(lines)} from {name}" for name, lines in found.items()) if found else ".")]
    for name, lines in found.items():
        report.append(f"{name}:")
        report += [f"  {line}" for line in lines[:UPDATE_LIST_LIMIT]]
        if len(lines) > UPDATE_LIST_LIMIT:
            report.append(f"  … and {len(lines) - UPDATE_LIST_LIMIT} more")
    if failed:
        report.append("Could not check: " + ", ".join(failed) + " (offline, or the source is not set up).")
    if any(_KERNEL.match(line.split()[0]) for line in found.get("distribution", [])):
        report.append("The kernel is among them: a restart will be needed afterwards.")
    reboot = pending_reboot()
    if reboot:
        report.append(f"A restart is already needed: {reboot}.")
    steps = []
    if "distribution" in found or "AUR" in found:
        steps.append("yay -Syu" if shutil.which("yay") else "sudo pacman -Syu")
    if "Flatpak" in found:
        steps.append("flatpak update -y")
    if steps:
        report.append("To update everything, run in a terminal (it asks for the password): " + " && ".join(steps))
    return "\n".join(report)


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
        Tool("check_updates", "What updates are waiting (distribution, AUR, Flatpak), whether a restart will be "
             "needed, and the one command that installs them all. Use before updating the computer, then run that "
             "command with run_in_terminal.", object_schema(), RISK_READ, check_updates,
             summarize=lambda a: "Check for updates"),
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
