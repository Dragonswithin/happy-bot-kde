"""The Happy Bot app: whether it is running, starting it, starting it at login, and asking it to show itself.

Happy Bot runs as an application of its own, not only as a panel widget: ``happy-bot-app``
(``launchers/``) starts the widget outside the panel with Plasma's ``plasmawindowed``, where it
shows only the floating Happy Bot, and the "Happy Bot" entry in the application menu runs that
launcher. This module is the daemon's side of it:

- ``running`` looks for that process (``APP_COMMAND``) among the user's processes.
- ``start`` runs ``happy-bot-app`` detached from the daemon, so the app outlives a daemon restart.
- ``autostart_enabled`` and ``set_autostart`` add or remove the app's entry in
  ``$XDG_CONFIG_HOME/autostart``, so it starts when the user logs in.
- ``Waker`` lets a second launch (the menu entry or the hotkey while the app runs) and the panel
  widget reach the running app: ``happy-bot app show`` (or ``settings``) calls ``POST /app/show``
  (``notify``) with what to show, ``open`` (the floating Happy Bot) or ``settings`` (its settings,
  which hold nearly all of Happy Bot's settings); the app waits on ``GET /app/wait`` (``wait``),
  which answers as soon as the count of requests grows or after ``WAIT_SECONDS``, so the app asks
  again. The answer carries the last request's action and age, so an app that was just started
  for a request (``start``, then ``notify``) still acts on it. Only the app waits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

APPLET_ID = "io.github.dragonswithin.happybot"
APP_COMMAND = ["plasmawindowed", "--statusnotifier", APPLET_ID]
DESKTOP_FILE = f"{APPLET_ID}.desktop"
WAIT_SECONDS = 25.0


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def autostart_path() -> Path:
    return _config_home() / "autostart" / DESKTOP_FILE


def menu_entry_path() -> Path:
    return _data_home() / "applications" / DESKTOP_FILE


def running() -> bool:
    """Whether the Happy Bot app (the widget in ``plasmawindowed``) runs for this user."""
    pattern = "^" + " ".join(APP_COMMAND) + "$"
    try:
        found = subprocess.run(["pgrep", "-u", str(os.getuid()), "-f", pattern], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return found.returncode == 0


def start() -> None:
    """Start the app (``happy-bot-app``) in its own session, so it is not tied to the daemon."""
    launcher = shutil.which("happy-bot-app") or str(Path.home() / ".local" / "bin" / "happy-bot-app")
    subprocess.Popen([launcher], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def autostart_enabled() -> bool:
    return autostart_path().exists()


def set_autostart(enabled: bool) -> None:
    """Add or remove the login entry, a copy of the installed menu entry; raises ``OSError`` if it cannot."""
    target = autostart_path()
    if not enabled:
        target.unlink(missing_ok=True)
        return
    text = menu_entry_path().read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


ACTIONS = ("open", "settings")


class Waker:
    """Counts "show yourself" requests; the app waits until the count passes the one it has seen."""

    def __init__(self) -> None:
        self._count = 0
        self._action = "open"
        self._at = 0.0
        self._changed = threading.Condition()

    def notify(self, action: str = "open") -> int:
        with self._changed:
            self._count += 1
            self._action = action if action in ACTIONS else "open"
            self._at = time.monotonic()
            self._changed.notify_all()
            return self._count

    def wait(self, seen: int, timeout: float = WAIT_SECONDS) -> dict[str, object]:
        """``{"count", "action", "age"}`` once the count is above ``seen`` (at once for -1), else after ``timeout``.

        ``age`` is how many seconds ago the last request came (-1 when there was none).
        """
        with self._changed:
            if seen >= 0:
                self._changed.wait_for(lambda: self._count > seen, timeout)
            age = round(time.monotonic() - self._at, 1) if self._count else -1
            return {"count": self._count, "action": self._action, "age": age}


waker = Waker()
