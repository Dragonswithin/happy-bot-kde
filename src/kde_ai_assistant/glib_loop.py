"""One shared GLib main loop for the daemon's DBus-based features.

``kwin_bridge`` (receiving results from KWin scripts) and ``input_portal``
(receiving portal responses) both need DBus callbacks delivered, which GLib
does from a running main loop on the default main context. ``ensure_running``
starts that loop once, on a daemon thread, for the life of the process.

Requires PyGObject; importing this module does not, calling the function does.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_started = False


def ensure_running() -> None:
    """Start the default-context GLib main loop on a daemon thread if it is not running."""
    global _started
    with _lock:
        if _started:
            return
        from gi.repository import GLib

        threading.Thread(target=GLib.MainLoop().run, name="glib-main-loop", daemon=True).start()
        _started = True
