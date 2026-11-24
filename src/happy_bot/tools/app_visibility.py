"""Makes sure an installed application actually shows up in the Plasma launcher.

Installing a package is not the end of the job: the launcher only lists an
application whose ``.desktop`` entry is in a folder the Plasma shell searches
(its ``XDG_DATA_DIRS``, plus ``~/.local/share``) and that is in the menu
cache (KDE's ksycoca). Both can be out of date after an install, most often
the first time something is installed per-user with Flatpak: the shell keeps
the folder list it started with.

- ``verify_app_install`` (read) finds the application's launcher entry,
  checks that its folder is one the running shell searches and that the menu
  cache built for that folder list contains it, and says how to open it.
- ``refresh_app_menu`` (change) rebuilds the menu cache for the session's
  current folder list. When the running shell is missing a folder that holds
  applications, the session environment is updated and a restart of the
  Plasma shell is scheduled for just after the current request ends:
  restarting it mid-request would close the popup's connection and stop the
  request. ``run_after_turn`` performs that scheduled restart; the daemon
  calls it when a turn finishes.

The menu cache is keyed by the folder list, so the cache built here is the
one the restarted shell will load; checking it confirms the entry will be
listed before the restart happens.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..desktop_context import run_command
from .apps import installed_applications, match_applications
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

DEFAULT_DATA_DIRS = ("/usr/local/share", "/usr/share")
FLATPAK_DIRS = (str(Path.home() / ".local/share/flatpak/exports/share"), "/var/lib/flatpak/exports/share")
RESTART_DELAY_SECONDS = 2.0
_restart_lock = threading.Lock()
_restart_pending = False


def _split(value: str) -> list[str]:
    return [item.rstrip("/") for item in value.split(":") if item]


def data_home() -> str:
    return (os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")).rstrip("/")


def session_data_dirs() -> list[str]:
    """The session's current application folder list (the user manager's environment), plus Flatpak's."""
    output = run_command(["systemctl", "--user", "show-environment"], timeout=5)["stdout"]
    value = next((line.split("=", 1)[1] for line in output.splitlines() if line.startswith("XDG_DATA_DIRS=")), "")
    dirs = _split(value) or list(DEFAULT_DATA_DIRS)
    for extra in FLATPAK_DIRS:
        if extra not in dirs and os.path.isdir(extra):
            dirs.insert(0, extra)
    return dirs


def shell_data_dirs() -> tuple[int, list[str]] | None:
    """``(pid, folders)`` the running Plasma shell searches, or None when it is not running."""
    result = run_command(["pgrep", "-u", str(os.getuid()), "-x", "plasmashell"], timeout=5)
    pids = [int(item) for item in result["stdout"].split() if item.isdigit()]
    if not pids:
        return None
    try:
        environ = Path(f"/proc/{pids[0]}/environ").read_bytes().split(b"\0")
    except OSError:
        return None
    value = next((item[len(b"XDG_DATA_DIRS="):].decode(errors="replace") for item in environ
                  if item.startswith(b"XDG_DATA_DIRS=")), "")
    return pids[0], _split(value) or list(DEFAULT_DATA_DIRS)


def menu_cache_contains(desktop_id: str, since: float = 0) -> bool:
    """Whether a menu cache written after ``since`` lists ``desktop_id``."""
    needle = desktop_id.removesuffix(".desktop").encode("utf-16-be")
    for path in glob.glob(str(Path.home() / ".cache" / "ksycoca6_*")):
        try:
            if os.path.getmtime(path) >= since and needle in Path(path).read_bytes():
                return True
        except OSError:
            continue
    return False


def rebuild_menu_cache(dirs: list[str]) -> bool:
    if not shutil.which("kbuildsycoca6"):
        return False
    environment = {**os.environ, "XDG_DATA_DIRS": ":".join(dirs)}
    try:
        return subprocess.run(["kbuildsycoca6"], env=environment, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=60, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _find(name: str) -> dict[str, str]:
    if not isinstance(name, str) or not name.strip():
        raise ToolFailure("'name' is required: the application's name, for example 'Ladybird'")
    matches = match_applications(name, installed_applications())
    if not matches:
        raise ToolFailure(
            f"No launcher entry for '{name}' exists in any application folder. Either the install did not finish, "
            "or the package has no desktop entry (check that the package is installed and how it is started).")
    return matches[0]


def _root_of(entry_path: str) -> str:
    parts = Path(entry_path).parts
    index = len(parts) - 1 - list(reversed(parts)).index("applications")
    return str(Path(*parts[:index])).rstrip("/")


def _how_to_open(app: dict[str, str]) -> str:
    return f"Open it from the application launcher by searching for “{app['name']}”."


def verify_app_install(arguments: dict[str, Any]) -> str:
    app = _find(arguments.get("name"))
    root = _root_of(app["path"])
    lines = [f"Found {app['name']}: launcher entry {app['path']}."]
    shell = shell_data_dirs()
    if shell is None:
        lines.append("The Plasma shell is not running, so the launcher could not be checked.")
        return "\n".join(lines)
    _pid, dirs = shell
    searched = root == data_home() or root in dirs
    entry_time = os.path.getmtime(app["path"]) if os.path.exists(app["path"]) else 0
    cached = menu_cache_contains(app["id"], since=entry_time - 1)
    if searched and cached:
        lines.append("It is visible in the launcher. " + _how_to_open(app))
    elif not searched:
        lines.append(f"NOT visible yet: the running Plasma shell does not search {root}. Call refresh_app_menu.")
    else:
        lines.append("NOT visible yet: the menu cache has not picked it up. Call refresh_app_menu.")
    return "\n".join(lines)


def _schedule_restart() -> None:
    global _restart_pending
    with _restart_lock:
        _restart_pending = True


def run_after_turn() -> bool:
    """Restart the Plasma shell if a tool asked for it during the turn. Returns whether one was started."""
    global _restart_pending
    with _restart_lock:
        pending, _restart_pending = _restart_pending, False
    if not pending:
        return False

    def restart() -> None:
        time.sleep(RESTART_DELAY_SECONDS)
        run_command(["systemctl", "--user", "restart", "plasma-plasmashell.service"], timeout=30)

    threading.Thread(target=restart, name="restart-plasmashell", daemon=True).start()
    return True


def refresh_app_menu(arguments: dict[str, Any]) -> str:
    app = _find(arguments.get("name")) if arguments.get("name") else None
    dirs = session_data_dirs()
    shell = shell_data_dirs()
    missing = [item for item in dirs if shell is not None and item not in shell[1]
               and os.path.isdir(os.path.join(item, "applications"))]
    started = time.time()
    if not rebuild_menu_cache(dirs):
        raise ToolFailure("the menu cache could not be rebuilt (kbuildsycoca6 failed or is missing)")
    report = ["Rebuilt the application menu cache."]
    if app is not None:
        if not menu_cache_contains(app["id"], since=started - 1):
            raise ToolFailure(f"the rebuilt menu cache still does not list {app['name']} ({app['path']})")
        report.append(f"{app['name']} is in it.")
    if missing:
        run_command(["systemctl", "--user", "set-environment", "XDG_DATA_DIRS=" + ":".join(dirs)], timeout=5)
        _schedule_restart()
        report.append(
            "The running Plasma shell does not search " + ", ".join(missing) + ", so the panel will restart "
            f"about {RESTART_DELAY_SECONDS:g} seconds after this request ends (it flickers briefly). Tell the user.")
    if app is not None:
        report.append(_how_to_open(app) + (" (after the panel restarts)" if missing else ""))
    return " ".join(report)


def app_visibility_tools() -> list[Tool]:
    name = {"type": "string", "description": "The application's name, for example 'Ladybird'"}
    return [
        Tool("verify_app_install", "After installing an application, check that it is really installed and visible "
             "in the Plasma application launcher, and how to open it.", object_schema({"name": name}, ["name"]),
             RISK_READ, verify_app_install, summarize=lambda a: f"Checked that {a.get('name', '')} is in the launcher"),
        Tool("refresh_app_menu", "Make newly installed applications appear in the launcher: rebuilds the menu "
             "cache and, if needed, restarts the Plasma panel right after this request.",
             object_schema({"name": name}), RISK_CHANGE, refresh_app_menu,
             summarize=lambda a: "Refresh the application launcher" + (f" for {a['name']}" if a.get("name") else "")),
    ]
