"""Actions the daemon performs on the desktop for the user.

Counterpart of ``desktop_context`` (which only reads). Each function here
changes something the user can see, runs as the user, and reports failure by
raising ``DesktopActionError`` with a message meant for the user.

``open_location`` hands a file, folder or web link to the desktop's default
handler through ``xdg-open``. The child is detached into its own session so
the opened application outlives the request and the daemon; its output is
discarded. Only absolute paths and http(s) URLs are accepted, so a caller
cannot smuggle options or other URL schemes to the handler.

``open_assistant_popup`` opens the panel applet's popup from outside it (a
notification's "Open" button): Plasma registers an "activate widget <id>"
global-shortcut action for every applet, and invoking that action through
KGlobalAccel's DBus interface does what the shortcut does. The applet's
widget id is looked up through the Plasma shell's scripting interface.
"""

from __future__ import annotations

import os
import shutil
import subprocess


APPLET_ID = "io.github.dragonswithin.kdeaiassistant"
_FIND_WIDGET = ("panels().concat(desktops()).forEach(function (c) { c.widgets().forEach(function (w) {"
                " if (w.type == '%s') { print(w.id + ' '); } }); });" % APPLET_ID)


class DesktopActionError(RuntimeError):
    """The action could not be carried out; the message is user-facing."""


def _run(command: list[str]) -> str:
    if not shutil.which(command[0]):
        raise DesktopActionError(f"'{command[0]}' is not installed")
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if completed.returncode != 0:
        raise DesktopActionError((completed.stderr or completed.stdout).strip() or f"{command[0]} failed")
    return completed.stdout


def open_assistant_popup() -> None:
    """Open the assistant's popup, as its keyboard shortcut would."""
    ids = _run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", _FIND_WIDGET]).split()
    if not ids:
        raise DesktopActionError("the AI Assistant is not on any panel")
    _run(["qdbus6", "org.kde.kglobalaccel", "/component/plasmashell", "org.kde.kglobalaccel.Component.invokeShortcut",
          f"activate widget {ids[0]}"])


def open_location(location: str) -> None:
    """Open an absolute path or http(s) URL with the default application."""
    target = location.strip()
    is_link = target.startswith(("http://", "https://"))
    if not is_link:
        if not target.startswith("/"):
            raise DesktopActionError("only files, folders and web links can be opened")
        if not os.path.exists(target):
            raise DesktopActionError(f"{target} no longer exists")
    opener = shutil.which("xdg-open")
    if not opener:
        raise DesktopActionError("xdg-open is not installed")
    try:
        subprocess.Popen(
            [opener, target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise DesktopActionError(f"could not open {target}: {exc}") from exc
