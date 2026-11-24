"""Runs small JavaScript snippets inside KWin and returns their result.

KWin exposes window state and window management to scripts, not to plain
DBus calls (its one DBus query, ``queryWindowInfo``, is an interactive
click-to-pick tool). This module is the assistant's way in: it writes a
snippet to a temporary file, asks KWin to load and run it, and receives the
snippet's return value through a DBus method call that the script makes back
to this process.

How a call works (``KWinBridge.run``):

1. The snippet is wrapped so its return value, or the exception it throws,
   is JSON-encoded and sent with ``callDBus`` to this process's unique bus
   name, tagged with a one-time token.
2. The file is loaded with ``org.kde.kwin.Scripting.loadScript`` under a
   one-time plugin name and started with ``org.kde.kwin.Script.run``.
3. The caller waits for the token's reply, then the script is unloaded and
   the file removed, whether or not a reply arrived.

Dependency: PyGObject (``gi``), for ``Gio`` DBus. It is imported lazily so the
rest of the daemon works without it; ``KWinBridge.run`` then raises
``KWinUnavailable`` with an explanation.

Threading: the DBus object is served by the shared GLib main loop
(``glib_loop``), started on first use. ``run`` may be called from any thread; calls are
serialised by a lock because scripts are cheap and ordering keeps window
operations predictable. ``run`` blocks up to ``timeout`` seconds.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from . import glib_loop

BRIDGE_PATH = "/io/github/dragonswithin/HappyBot/KWinBridge"
BRIDGE_INTERFACE = "io.github.dragonswithin.HappyBot.KWinBridge"
DEFAULT_TIMEOUT_SECONDS = 5.0
_INTROSPECTION = f"""
<node>
  <interface name="{BRIDGE_INTERFACE}">
    <method name="Result">
      <arg type="s" name="token" direction="in"/>
      <arg type="s" name="payload" direction="in"/>
    </method>
  </interface>
</node>
"""
_WRAPPER = """
(function () {
    var payload;
    try {
        var value = (function () {
%(body)s
        })();
        payload = JSON.stringify({ ok: true, value: value === undefined ? null : value });
    } catch (error) {
        payload = JSON.stringify({ ok: false, error: String(error) });
    }
    callDBus("%(bus)s", "%(path)s", "%(interface)s", "Result", "%(token)s", payload);
})();
"""


class KWinUnavailable(RuntimeError):
    """KWin scripting could not be used; the message says why."""


class KWinScriptError(RuntimeError):
    """The snippet threw inside KWin."""


class KWinBridge:
    def __init__(self, runtime_dir: Path) -> None:
        self._runtime_dir = runtime_dir
        self._call_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._waiters: dict[str, tuple[threading.Event, list[str]]] = {}
        self._connection: Any = None
        self._gio: Any = None
        self._glib: Any = None

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._connection is not None:
                return
            try:
                import gi

                gi.require_version("Gio", "2.0")
                from gi.repository import Gio, GLib
            except (ImportError, ValueError) as error:
                raise KWinUnavailable(f"PyGObject is needed to talk to KWin and is not installed ({error})") from error
            try:
                connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            except GLib.Error as error:
                raise KWinUnavailable(f"no desktop session bus: {error.message}") from error
            node = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION)
            connection.register_object(BRIDGE_PATH, node.interfaces[0], self._on_method_call, None, None)
            glib_loop.ensure_running()
            self._gio, self._glib, self._connection = Gio, GLib, connection

    def _on_method_call(self, connection, sender, path, interface, method, parameters, invocation) -> None:
        if method == "Result":
            token, payload = parameters.unpack()
            waiter = self._waiters.get(token)
            if waiter is not None:
                waiter[1].append(payload)
                waiter[0].set()
        invocation.return_value(None)

    def _call(self, path: str, interface: str, method: str, signature: str | None, arguments: tuple) -> Any:
        variant = self._glib.Variant(signature, arguments) if signature else None
        try:
            reply = self._connection.call_sync(
                "org.kde.KWin", path, interface, method, variant, None,
                self._gio.DBusCallFlags.NONE, 4000, None)
        except self._glib.Error as error:
            raise KWinUnavailable(f"KWin did not accept the request: {error.message}") from error
        return reply.unpack() if reply is not None else ()

    def run(self, body: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Any:
        """Run ``body`` (statements ending in ``return <json-able value>;``) inside KWin.

        Returns the decoded value. Raises ``KWinScriptError`` if the snippet
        threw and ``KWinUnavailable`` if KWin could not be reached or did not
        answer in time.
        """
        self._ensure_started()
        token = secrets.token_hex(12)
        plugin = f"happybot_{token}"
        script_file = self._runtime_dir / f"kwin-{token}.js"
        source = _WRAPPER % {
            "body": body, "bus": self._connection.get_unique_name(), "path": BRIDGE_PATH,
            "interface": BRIDGE_INTERFACE, "token": token,
        }
        done = threading.Event()
        payloads: list[str] = []
        with self._call_lock:
            self._waiters[token] = (done, payloads)
            descriptor = os.open(script_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(source)
            try:
                (script_id,) = self._call(
                    "/Scripting", "org.kde.kwin.Scripting", "loadScript", "(ss)", (str(script_file), plugin))
                if script_id < 0:
                    raise KWinUnavailable("KWin refused to load the script")
                self._call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run", None, ())
                answered = done.wait(timeout)
            finally:
                self._waiters.pop(token, None)
                try:
                    self._call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "(s)", (plugin,))
                except KWinUnavailable:
                    pass
                try:
                    script_file.unlink()
                except OSError:
                    pass
        if not answered:
            raise KWinUnavailable(f"KWin did not answer within {timeout:g}s")
        result = json.loads(payloads[0])
        if not result.get("ok"):
            raise KWinScriptError(str(result.get("error")))
        return result.get("value")


_shared: KWinBridge | None = None
_shared_lock = threading.Lock()


def shared() -> KWinBridge:
    """The process-wide bridge, writing its temporary scripts to the runtime directory."""
    global _shared
    with _shared_lock:
        if _shared is None:
            from .runtime_paths import ensure_runtime_root

            _shared = KWinBridge(ensure_runtime_root())
        return _shared


# Snippets shared by context capture and tools. Each returns plain JSON data.
WINDOW_FIELDS_JS = """
function describe(w) {
    var g = w.frameGeometry;
    return {
        id: String(w.internalId), title: w.caption, app: w.resourceClass, pid: w.pid,
        x: Math.round(g.x), y: Math.round(g.y), width: Math.round(g.width), height: Math.round(g.height),
        minimized: w.minimized, fullscreen: w.fullScreen, active: w === workspace.activeWindow,
        screen: w.output ? w.output.name : "", desktop: w.desktops.length ? w.desktops[0].name : "all"
    };
}
"""
# The window the user is working in. While they type in the panel bar the
# active window is the panel itself, so in that case this is the topmost
# ordinary window on the current desktop: the one they were just using.
# Happy Bot's own windows (the floating Happy Bot, run by plasmawindowed, which
# KWin counts as an ordinary window) and Plasma's are never that window.
CURRENT_WINDOW_JS = """
function isUserWindow(w) {
    var own = ["plasmawindowed", "plasmashell", "org.kde.plasmashell"];
    return (w.normalWindow || w.dialog) && own.indexOf(String(w.resourceClass)) < 0;
}
function currentWindow() {
    var active = workspace.activeWindow;
    if (active && isUserWindow(active)) { return active; }
    var stack = workspace.stackingOrder;
    for (var i = stack.length - 1; i >= 0; i--) {
        var w = stack[i];
        if (isUserWindow(w) && !w.minimized && (w.onAllDesktops || w.desktops.indexOf(workspace.currentDesktop) >= 0)) {
            return w;
        }
    }
    return null;
}
"""
ACTIVE_WINDOW_JS = WINDOW_FIELDS_JS + CURRENT_WINDOW_JS + """
var current = currentWindow();
return current ? describe(current) : null;
"""
LIST_WINDOWS_JS = WINDOW_FIELDS_JS + """
return workspace.windowList().filter(function (w) { return w.normalWindow; }).map(describe);
"""
