"""Reads properties and lists services on the user's session DBus.

Media players (MPRIS) and KDE Connect publish their state as DBus
properties whose values are nested dictionaries (``a{sv}``), which the
command-line tools print in a form that is hard to parse reliably. This
module asks the bus directly through PyGObject's ``Gio`` (``call``, ``names``,
``properties``, ``set_property``) and returns plain
Python values (``GLib.Variant.unpack``).

``gi`` is imported lazily, as in ``kwin_bridge``: without PyGObject the
callers get ``DBusUnavailable`` with the reason and everything else keeps
working. Calls are synchronous with a short timeout (``TIMEOUT_MS``) and run
on the calling thread; a service that does not answer raises ``DBusError``.
"""

from __future__ import annotations

from typing import Any

TIMEOUT_MS = 3000


class DBusUnavailable(RuntimeError):
    """PyGObject or the session bus is not available."""


class DBusError(RuntimeError):
    """A DBus call failed; the message is the service's error."""


def _bus():
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError) as error:
        raise DBusUnavailable(f"PyGObject is not installed ({error})") from error
    try:
        return Gio, GLib, Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as error:
        raise DBusUnavailable(f"the session bus is not reachable: {error.message}") from error


def call(service: str, path: str, interface: str, method: str, signature: str = "", arguments: tuple = ()) -> Any:
    """Call a method and return its unpacked reply (a tuple), or raise ``DBusError``."""
    Gio, GLib, bus = _bus()
    parameters = GLib.Variant(f"({signature})", arguments) if signature else None
    try:
        reply = bus.call_sync(service, path, interface, method, parameters, None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
    except GLib.Error as error:
        raise DBusError(error.message) from error
    return reply.unpack() if reply is not None else ()


def names(prefix: str = "") -> list[str]:
    """Well-known names on the session bus that start with ``prefix``, sorted."""
    listed = call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames")[0]
    return sorted(name for name in listed if name.startswith(prefix))


def properties(service: str, path: str, interface: str) -> dict[str, Any]:
    """Every property of ``interface`` on the object, as plain Python values."""
    return call(service, path, "org.freedesktop.DBus.Properties", "GetAll", "s", (interface,))[0]


def set_property(service: str, path: str, interface: str, name: str, signature: str, value: Any) -> None:
    """Set one property; ``signature`` is the value's DBus type, for example ``s``."""
    Gio, GLib, bus = _bus()
    parameters = GLib.Variant("(ssv)", (interface, name, GLib.Variant(signature, value)))
    try:
        bus.call_sync(service, path, "org.freedesktop.DBus.Properties", "Set", parameters, None,
                      Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
    except GLib.Error as error:
        raise DBusError(error.message) from error
