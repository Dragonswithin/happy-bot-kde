"""Application tools: find installed applications, start one, open a file or link.

Applications are discovered from ``.desktop`` files in the standard XDG
application directories (system, per-user and Flatpak exports), the same
entries the launcher shows. Starting an application or opening a location is
risk ``change``: something new appears on screen and nothing is lost.

``launch_application`` takes a name the way a person would say it. An exact
name match wins; otherwise a single match on the name, generic name or
keywords is used; several plausible matches fail with the list so the model
can pick. Launching goes through ``gio launch``, detached so the application
outlives the daemon. ``open_folder`` asks the file manager over the
freedesktop ``FileManager1`` DBus interface to show a folder, or a file
selected in its folder; ``open_terminal`` opens the user's terminal in a
folder: the one chosen under Behaviour (``agent.terminal``, which
``app_tools`` is given), else the automatic choice
(``tools/shell.terminal_program``: KDE's default terminal when supported).
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .. import desktop_actions
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

MAX_LISTED = 25


def application_directories() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    roots = [data_home, *[Path(item) for item in data_dirs if item],
             Path("/var/lib/flatpak/exports/share"), data_home / "flatpak/exports/share"]
    seen: list[Path] = []
    for root in roots:
        directory = root / "applications"
        if directory not in seen:
            seen.append(directory)
    return seen


def installed_applications(directories: list[Path] | None = None) -> list[dict[str, str]]:
    """Launchable applications: ``{id, name, generic, keywords, comment, path}``.

    Earlier directories win, so a user's override hides the system entry.
    Entries marked hidden or not for display, and non-applications, are skipped.
    """
    found: dict[str, dict[str, str]] = {}
    for directory in directories or application_directories():
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.desktop")):
            desktop_id = str(path.relative_to(directory)).replace("/", "-")
            if desktop_id in found:
                continue
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
                continue
            if entry.get("Type", "Application") != "Application" or not entry.get("Exec"):
                continue
            if entry.get("NoDisplay", "false").lower() == "true" or entry.get("Hidden", "false").lower() == "true":
                continue
            found[desktop_id] = {
                "id": desktop_id, "name": entry.get("Name", desktop_id), "generic": entry.get("GenericName", ""),
                "keywords": entry.get("Keywords", ""), "comment": entry.get("Comment", ""), "path": str(path),
            }
    return sorted(found.values(), key=lambda item: item["name"].lower())


def match_applications(query: str, applications: list[dict[str, str]]) -> list[dict[str, str]]:
    """Best matches for ``query``, strongest first: exact name, name prefix, then any field."""
    text = query.strip().lower()
    if not text:
        return []
    exact = [app for app in applications if text in (app["name"].lower(), app["id"].lower().removesuffix(".desktop"))]
    if exact:
        return exact
    prefix = [app for app in applications if app["name"].lower().startswith(text)]
    if prefix:
        return prefix
    words = text.split()
    return [
        app for app in applications
        if all(word in f"{app['name']} {app['generic']} {app['keywords']} {app['id']}".lower() for word in words)
    ]


def list_applications(arguments: dict[str, Any]) -> str:
    query = str(arguments.get("query") or "")
    applications = installed_applications()
    matches = match_applications(query, applications) if query.strip() else applications
    if not matches:
        return f"No installed application matches '{query}'."
    lines = [f"{app['name']}" + (f" ({app['generic']})" if app["generic"] else "") + f"  [{app['id']}]"
             for app in matches[:MAX_LISTED]]
    if len(matches) > MAX_LISTED:
        lines.append(f"[{len(matches) - MAX_LISTED} more; give a query to narrow down]")
    return "\n".join(lines)


def launch_application(arguments: dict[str, Any]) -> str:
    name = str(arguments.get("name") or "").strip()
    if not name:
        raise ToolFailure("'name' is required")
    matches = match_applications(name, installed_applications())
    if not matches:
        raise ToolFailure(f"no installed application matches '{name}'. Use list_applications to see what exists.")
    if len(matches) > 1:
        options = ", ".join(f"{app['name']} [{app['id']}]" for app in matches[:10])
        raise ToolFailure(f"several applications match '{name}': {options}. Give the exact name or id.")
    launcher = shutil.which("gio")
    if not launcher:
        raise ToolFailure("the 'gio' command is not installed, so applications cannot be started")
    try:
        subprocess.Popen([launcher, "launch", matches[0]["path"]], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as error:
        raise ToolFailure(f"could not start {matches[0]['name']}: {error}") from error
    return f"Started {matches[0]['name']}."


def open_location(arguments: dict[str, Any]) -> str:
    location = str(arguments.get("location") or "").strip()
    try:
        desktop_actions.open_location(os.path.expanduser(location))
    except desktop_actions.DesktopActionError as error:
        raise ToolFailure(str(error)) from error
    return f"Opened {location}."


def open_folder(arguments: dict[str, Any]) -> str:
    """Show a folder, or a file selected in its folder, in the user's file manager."""
    from .. import session_dbus

    path = os.path.abspath(os.path.expanduser(str(arguments.get("path") or "").strip()))
    if not os.path.exists(path):
        raise ToolFailure(f"{path} does not exist")
    method = "ShowFolders" if os.path.isdir(path) else "ShowItems"
    try:
        session_dbus.call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                          "org.freedesktop.FileManager1", method, "ass", ([Path(path).as_uri()], ""))
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"the file manager could not be asked to show it ({error})") from error
    return f"Showing {path} in the file manager."


def open_terminal(arguments: dict[str, Any], preferred: str = "") -> str:
    """Open the user's terminal (``preferred``, the Behaviour setting, else automatic) in a folder."""
    from .shell import terminal_name, terminal_program

    folder = os.path.abspath(os.path.expanduser(str(arguments.get("folder") or "~")))
    if not os.path.isdir(folder):
        raise ToolFailure(f"{folder} is not a folder")
    terminal = terminal_program(preferred)
    name = terminal_name(terminal)
    if name in ("konsole", "kwi"):
        command = [terminal, "--workdir", folder]
    elif name in ("gnome-terminal", "kgx"):
        command = [terminal, f"--working-directory={folder}"]
    else:
        command = [terminal]
    subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return f"Opened a terminal in {folder}."


def app_tools(terminal: str = "") -> list[Tool]:
    """The application tools; ``terminal`` is the user's ``agent.terminal`` setting ("" for automatic)."""
    return [
        Tool("list_applications", "List installed applications, optionally filtered by a query.",
             object_schema({"query": {"type": "string"}}), RISK_READ, list_applications),
        Tool("launch_application", "Start an installed application by name, for example 'Firefox' or 'Konsole'.",
             object_schema({"name": {"type": "string"}}, ["name"]), RISK_CHANGE, launch_application,
             summarize=lambda arguments: f"Start {arguments.get('name', '')}"),
        Tool("open_folder", "Show a folder, or a file selected inside its folder, in the file manager (Dolphin).",
             object_schema({"path": {"type": "string"}}, ["path"]), RISK_CHANGE, open_folder,
             summarize=lambda arguments: f"Show {arguments.get('path', '')} in the file manager"),
        Tool("open_terminal", "Open a terminal window in a folder for the user to work in.",
             object_schema({"folder": {"type": "string"}}), RISK_CHANGE,
             lambda arguments: open_terminal(arguments, terminal),
             summarize=lambda arguments: f"Open a terminal in {arguments.get('folder') or 'the home folder'}"),
        Tool("open_location", "Open a file or folder with its default application, or a web link in the browser.",
             object_schema({"location": {"type": "string", "description": "Absolute path, ~ path, or http(s) URL"}},
                           ["location"]), RISK_CHANGE, open_location,
             summarize=lambda arguments: f"Open {arguments.get('location', '')}"),
    ]
