"""Actions on an application found by the search bar: update it, uninstall it, start it at login.

The search bar's application results (``quick_results``, action ``launch``
with the ``.desktop`` file as target) get a menu. ``describe(path)`` says what
that menu can offer for one application: which package provides it
(``package_of``), whether it starts at login, and the update and uninstall
commands. ``carry_out(path, action, terminal)`` does one of them.

Packages: an entry under a Flatpak ``exports`` folder is that Flatpak app (its
file name is the app id); any other is looked up with ``pacman -Qqo``, and a
package pacman lists as foreign (``pacman -Qqm``) came from the AUR. An entry
no package owns (one the user made) offers only starting at login.

Updating and uninstalling go through the user's package manager in a
terminal window, never silently, so the user sees what happens and confirms
it there (the package manager's own question, and the password for system
packages): with Shelly installed, ``shelly update|remove standard|aur|flatpak
NAME``; otherwise ``flatpak update|uninstall ID``, ``yay -S|-Rs NAME`` for
the AUR, and for distribution packages ``sudo pacman -Rs NAME`` to remove and
``sudo pacman -Syu`` to update, because Arch does not support updating one
package alone (Shelly asks about that itself). The terminal is the one chosen
under Behaviour (``agent.terminal``) or KDE's default
(``tools.shell.terminal_program``); the window stays open when the command
ends. Opening the window does not wait for the command.

Starting at login: the application's entry in ``$XDG_CONFIG_HOME/autostart``
(a copy of its menu entry), as System Settings' Autostart page makes it. An
application the system starts at login (``/etc/xdg/autostart``) is turned
off with a user entry saying ``Hidden=true``, the standard way to override it.

Commands are built with ``shlex.quote`` from names read from the system, not
typed by the user. Every action is written to the action log by the caller
(``daemon_routes.quick_app_action``).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

SYSTEM_AUTOSTART = Path("/etc/xdg/autostart")
ACTIONS = ("update", "uninstall", "autostart_on", "autostart_off")
_FLATPAK_EXPORT = re.compile(r"/flatpak/exports/share/applications/([A-Za-z0-9_.-]+)\.desktop$")


class AppActionError(RuntimeError):
    """The action could not be done; the message says why, for the user."""


def _autostart_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"


def _run(command: list[str]) -> tuple[int, str]:
    if not shutil.which(command[0]):
        return 127, ""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return done.returncode, done.stdout.strip()


def package_of(path: str) -> dict[str, str]:
    """``{"source": "flatpak"|"standard"|"aur"|"", "name": ...}`` for the package providing the entry."""
    flatpak = _FLATPAK_EXPORT.search(path)
    if flatpak:
        return {"source": "flatpak", "name": flatpak.group(1)}
    code, owner = _run(["pacman", "-Qqo", path])
    if code != 0 or not owner:
        return {"source": "", "name": ""}
    name = owner.splitlines()[0]
    foreign, _ = _run(["pacman", "-Qqm", name])
    return {"source": "aur" if foreign == 0 else "standard", "name": name}


def _commands(package: dict[str, str]) -> tuple[str, str]:
    """The update and uninstall commands for a package ("" where there is none)."""
    source, name = package["source"], shlex.quote(package["name"])
    if not source:
        return "", ""
    if shutil.which("shelly"):
        return f"shelly update {source} {name}", f"shelly remove {source} {name}"
    if source == "flatpak":
        return f"flatpak update {name}", f"flatpak uninstall {name}"
    if source == "aur":
        return (f"yay -S {name}" if shutil.which("yay") else ""), f"sudo pacman -Rs {name}"
    return "sudo pacman -Syu", f"sudo pacman -Rs {name}"


def _entry_name(path: str) -> str:
    return Path(path).name


def _hidden(entry: Path) -> bool:
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return re.search(r"^Hidden\s*=\s*true\s*$", text, re.M | re.I) is not None


def starts_at_login(path: str) -> bool:
    user_entry = _autostart_dir() / _entry_name(path)
    if user_entry.is_file():
        return not _hidden(user_entry)
    return (SYSTEM_AUTOSTART / _entry_name(path)).is_file()


def set_starts_at_login(path: str, enabled: bool) -> None:
    """Turn starting at login on or off; raises ``AppActionError`` if it cannot."""
    name = _entry_name(path)
    user_entry, system_entry = _autostart_dir() / name, SYSTEM_AUTOSTART / name
    try:
        if enabled:
            user_entry.unlink(missing_ok=True)
            if not system_entry.is_file():
                user_entry.parent.mkdir(parents=True, exist_ok=True)
                user_entry.write_text(Path(path).read_text(encoding="utf-8"), encoding="utf-8")
        elif system_entry.is_file():
            user_entry.parent.mkdir(parents=True, exist_ok=True)
            user_entry.write_text(system_entry.read_text(encoding="utf-8").rstrip("\n") + "\nHidden=true\n",
                                  encoding="utf-8")
        else:
            user_entry.unlink(missing_ok=True)
    except (OSError, UnicodeDecodeError) as error:
        raise AppActionError(f"the login entry could not be changed ({error})") from error


def _check(path: str) -> None:
    if not path.endswith(".desktop") or not Path(path).is_file():
        raise AppActionError("that application is no longer installed")


def describe(path: str) -> dict[str, Any]:
    """What the menu offers for the application whose entry is ``path``."""
    _check(path)
    package = package_of(path)
    update, uninstall = _commands(package)
    return {"package": package["name"], "source": package["source"], "update": update, "uninstall": uninstall,
            "autostart": starts_at_login(path)}


def open_terminal(command: str, terminal: str = "") -> None:
    """Show a terminal window running ``command``; returns once the window is started."""
    from .tools.registry import ToolFailure
    from .tools.shell import terminal_command, terminal_program

    try:
        argv = terminal_command(terminal_program(terminal), command, str(Path.home()))
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except (ToolFailure, OSError) as error:
        raise AppActionError(f"no terminal window could be opened ({error})") from error


def carry_out(path: str, action: str, terminal: str = "") -> str:
    """Do one of ``ACTIONS`` for the application; returns what was done or raises ``AppActionError``."""
    if action not in ACTIONS:
        raise AppActionError(f"unknown action {action!r}")
    _check(path)
    if action in ("autostart_on", "autostart_off"):
        set_starts_at_login(path, action == "autostart_on")
        return f"{Path(path).stem} {'starts' if action == 'autostart_on' else 'no longer starts'} at login"
    update, uninstall = _commands(package_of(path))
    command = update if action == "update" else uninstall
    if not command:
        raise AppActionError("Happy Bot does not know how to " + action + " this application")
    open_terminal(command, terminal)
    return f"Opened a terminal: {command}"
