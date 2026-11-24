"""Workspace tools: virtual desktops, activities, show the desktop, close other windows, saved window layouts.

Virtual desktops use KWin's ``/VirtualDesktopManager`` and activities the
Activity Manager (``org.kde.ActivityManager``), both over the session DBus
(``session_dbus``). Showing the desktop and closing other windows run small
scripts inside KWin through ``kwin_bridge``, like the window tools.

Saved layouts ("coding layout") live in the daemon's settings as
``layouts``: a name and, per window, its application and place. Their schema
is validated here (``validate_layouts``, called by ``settings.py``). Saving
reads where the open windows are now; restoring moves the open windows of
those applications back and names the applications that are not running, so
the model can start them and restore again. The layout tools change
settings, so like the routine tools they are built with the daemon's
``read_settings`` and ``update_settings`` (``layout_tools``).

``find_window_with_text`` looks for words in window titles and then in what
each window shows, read through the accessibility tree (``accessibility``,
at most ``MAX_SEARCHED_WINDOWS`` windows).

Risk: listing and finding are ``read``; everything else is ``change``. Closing windows
asks each application to close, so ones with unsaved work show their own
prompt; deleting a saved layout is ``danger``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .. import kwin_bridge, session_dbus
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

DESKTOPS = ("org.kde.KWin", "/VirtualDesktopManager", "org.kde.KWin.VirtualDesktopManager")
ACTIVITIES = ("org.kde.ActivityManager", "/ActivityManager/Activities", "org.kde.ActivityManager.Activities")
_NAME = re.compile(r"^[A-Za-z0-9 _.-]{1,60}$")
_GEOMETRY_KEYS = ("x", "y", "width", "height")


class LayoutError(ValueError):
    """The ``layouts`` setting is not valid; the message says which layout and why."""


def validate_layouts(raw: Any) -> dict[str, list[dict[str, Any]]]:
    """Normalised ``layouts`` setting: ``{name: [{"app", "x", "y", "width", "height"}]}``, or ``LayoutError``."""
    if not isinstance(raw, dict):
        raise LayoutError("'layouts' must be an object")
    layouts = {}
    for name, windows in raw.items():
        if not isinstance(name, str) or not _NAME.match(name):
            raise LayoutError(f"layout '{name}': names use letters, digits, spaces, '_', '.' or '-' (max 60)")
        if not isinstance(windows, list) or not windows or len(windows) > 50:
            raise LayoutError(f"layout '{name}' must list 1 to 50 windows")
        cleaned = []
        for window in windows:
            if not isinstance(window, dict) or not isinstance(window.get("app"), str) or not window["app"]:
                raise LayoutError(f"layout '{name}': every window needs its application ('app')")
            for key in _GEOMETRY_KEYS:
                value = window.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 100000:
                    raise LayoutError(f"layout '{name}': '{key}' must be a whole number of pixels")
            cleaned.append({"app": window["app"], **{key: window[key] for key in _GEOMETRY_KEYS}})
        layouts[name] = cleaned
    return layouts


def _dbus(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(str(error)) from error


def _desktops() -> tuple[list[tuple[int, str, str]], str]:
    state = _dbus(lambda: session_dbus.properties(*DESKTOPS))
    return sorted(state.get("desktops") or []), state.get("current", "")


def list_workspaces(arguments: dict[str, Any]) -> str:
    desktops, current = _desktops()
    lines = ["Virtual desktops: " + ", ".join(
        f"{position + 1}. {name}{' (current)' if ident == current else ''}" for position, ident, name in desktops)]
    try:
        activities = session_dbus.call(*ACTIVITIES, "ListActivitiesWithInformation")[0]
        active = session_dbus.call(*ACTIVITIES, "CurrentActivity")[0]
        lines.append("Activities: " + ", ".join(f"{item[1]}{' (current)' if item[0] == active else ''}" for item in activities))
    except (session_dbus.DBusUnavailable, session_dbus.DBusError):
        pass
    return "\n".join(lines)


def _desktop_id(wanted: Any) -> tuple[str, str]:
    desktops, _ = _desktops()
    for position, ident, name in desktops:
        if str(wanted).strip().lower() in (str(position + 1), name.lower()):
            return ident, name
    raise ToolFailure(f"there is no virtual desktop '{wanted}'. {list_workspaces({})}")


def desktop_action(arguments: dict[str, Any]) -> str:
    action = arguments.get("action")
    if action == "switch":
        ident, name = _desktop_id(arguments.get("desktop"))
        _dbus(lambda: session_dbus.set_property(*DESKTOPS, "current", "s", ident))
        return f"Switched to desktop {name}."
    if action == "create":
        name = str(arguments.get("name") or "").strip() or "Desktop"
        desktops, _ = _desktops()
        _dbus(lambda: session_dbus.call(*DESKTOPS, "createDesktop", "us", (len(desktops), name)))
        return f"Created the virtual desktop {name}."
    if action == "rename":
        ident, old = _desktop_id(arguments.get("desktop"))
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ToolFailure("'name' is required")
        _dbus(lambda: session_dbus.call(*DESKTOPS, "setDesktopName", "ss", (ident, name)))
        return f"Renamed desktop {old} to {name}."
    if action == "remove":
        ident, name = _desktop_id(arguments.get("desktop"))
        if len(_desktops()[0]) < 2:
            raise ToolFailure("the last virtual desktop cannot be removed")
        _dbus(lambda: session_dbus.call(*DESKTOPS, "removeDesktop", "s", (ident,)))
        return f"Removed desktop {name}; its windows moved to another desktop."
    raise ToolFailure("'action' must be switch, create, rename or remove")


def activity_action(arguments: dict[str, Any]) -> str:
    action, name = arguments.get("action"), str(arguments.get("name") or "").strip()
    if not name:
        raise ToolFailure("'name' is required")
    activities = _dbus(lambda: session_dbus.call(*ACTIVITIES, "ListActivitiesWithInformation")[0])
    if action == "create":
        _dbus(lambda: session_dbus.call(*ACTIVITIES, "AddActivity", "s", (name,)))
        return f"Created the activity {name}."
    if action == "switch":
        found = [item for item in activities if item[1].lower() == name.lower()]
        if not found:
            raise ToolFailure(f"there is no activity '{name}'. {list_workspaces({})}")
        _dbus(lambda: session_dbus.call(*ACTIVITIES, "SetCurrentActivity", "s", (found[0][0],)))
        return f"Switched to the activity {found[0][1]}."
    raise ToolFailure("'action' must be switch or create")


def _kwin(script: str) -> Any:
    try:
        return kwin_bridge.shared().run(script)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError) as error:
        raise ToolFailure(str(error)) from error


def show_desktop(arguments: dict[str, Any]) -> str:
    show = arguments.get("show", True)
    if not isinstance(show, bool):
        raise ToolFailure("'show' must be true or false")
    _kwin(f"workspace.showingDesktop = {json.dumps(show)}; return true;")
    return "Showing the desktop." if show else "Windows are back."


def close_other_windows(arguments: dict[str, Any]) -> str:
    keep = [str(item).lower() for item in arguments.get("keep") or [] if str(item).strip()]
    script = kwin_bridge.WINDOW_FIELDS_JS + (
        "var keep = %s; var closed = [];"
        "workspace.windowList().forEach(function (w) {"
        "  if (!w.normalWindow) { return; }"
        "  var name = (w.resourceClass + ' ' + w.caption).toLowerCase();"
        "  for (var i = 0; i < keep.length; i++) { if (name.indexOf(keep[i]) >= 0) { return; } }"
        "  closed.push(w.resourceClass + ': ' + w.caption); w.closeWindow();"
        "}); return closed;" % json.dumps(keep))
    closed = _kwin(script)
    if not closed:
        return "No other windows were open."
    return f"Asked {len(closed)} windows to close (any with unsaved work will ask first):\n" + "\n".join(closed)


def layout_tools(read_settings: Callable[[], dict[str, Any]], update_settings) -> list[Tool]:
    from ..settings import SettingsError

    def save_layout(arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        windows = _kwin(kwin_bridge.LIST_WINDOWS_JS)
        apps = [str(item).lower() for item in arguments.get("apps") or []]
        chosen = [window for window in windows if not apps or any(app in window["app"].lower() for app in apps)]
        if not chosen:
            raise ToolFailure("no matching windows are open to save")
        entry = [{"app": window["app"], **{key: window[key] for key in _GEOMETRY_KEYS}} for window in chosen]
        try:
            update_settings(lambda settings: settings.setdefault("layouts", {}).__setitem__(name, entry))
        except SettingsError as error:
            raise ToolFailure(str(error)) from error
        return f"Saved the layout '{name}' with {len(entry)} windows: " + ", ".join(item["app"] for item in entry)

    def restore_layout(arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        layouts = read_settings().get("layouts", {})
        if name not in layouts:
            raise ToolFailure(f"there is no layout '{name}'. Saved: {', '.join(sorted(layouts)) or 'none'}")
        windows = _kwin(kwin_bridge.LIST_WINDOWS_JS)
        placed, missing, used = [], [], set()
        for wanted in layouts[name]:
            match = next((window for window in windows if window["app"] == wanted["app"] and window["id"] not in used), None)
            if match is None:
                missing.append(wanted["app"])
                continue
            used.add(match["id"])
            from .windows import _GEOMETRY_JS, _run as run_on_window
            run_on_window({"window": match["id"], **{key: wanted[key] for key in _GEOMETRY_KEYS}}, _GEOMETRY_JS)
            placed.append(wanted["app"])
        text = f"Placed {len(placed)} windows ({', '.join(placed) or 'none'})."
        return text + (f" Not running, so not placed: {', '.join(missing)}. Start them and restore again." if missing else "")

    def list_layouts(arguments: dict[str, Any]) -> str:
        layouts = read_settings().get("layouts", {})
        return "\n".join(f"{name}: {', '.join(item['app'] for item in windows)}" for name, windows in sorted(layouts.items())) \
            or "No layouts are saved."

    def delete_layout(arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        if name not in read_settings().get("layouts", {}):
            raise ToolFailure(f"there is no layout '{name}'")
        update_settings(lambda settings: settings["layouts"].pop(name, None))
        return f"Deleted the layout '{name}'."

    name = {"type": "string"}
    return [
        Tool("save_layout", "Remember where the open windows are as a named layout (optionally only some apps).",
             object_schema({"name": name, "apps": {"type": "array", "items": {"type": "string"}}}, ["name"]),
             RISK_CHANGE, save_layout, summarize=lambda a: f"Save the window layout '{a.get('name', '?')}'"),
        Tool("restore_layout", "Put windows back as a saved layout had them.",
             object_schema({"name": name}, ["name"]), RISK_CHANGE, restore_layout,
             summarize=lambda a: f"Restore the window layout '{a.get('name', '?')}'"),
        Tool("list_layouts", "The saved window layouts.", object_schema(), RISK_READ, list_layouts,
             summarize=lambda a: "List window layouts"),
        Tool("delete_layout", "Delete a saved window layout.", object_schema({"name": name}, ["name"]),
             RISK_DANGER, delete_layout, classify=lambda a: (RISK_DANGER, "deletes a layout you saved"),
             summarize=lambda a: f"Delete the window layout '{a.get('name', '?')}'"),
    ]


MAX_SEARCHED_WINDOWS = 15


def find_window_with_text(arguments: dict[str, Any]) -> str:
    """Windows whose title, or any text their application shows, contains the words."""
    from .. import accessibility

    wanted = " ".join(str(arguments.get("text") or "").split()).lower()
    if len(wanted) < 2:
        raise ToolFailure("'text' is required: words that appear in the window")
    found = []
    for window in _kwin(kwin_bridge.LIST_WINDOWS_JS)[:MAX_SEARCHED_WINDOWS]:
        if wanted in f"{window['title']} {window['app']}".lower():
            found.append(f"id {window['id']}  {window['app']}  \"{window['title']}\"  (in its title)")
            continue
        try:
            snapshot = accessibility.take_snapshot(int(window["pid"]), window["title"])
        except Exception:  # noqa: BLE001 - an app without an accessibility tree is simply skipped
            continue
        hit = next((element for element in snapshot.elements if wanted in f"{element.name} {element.value}".lower()), None)
        if hit is not None:
            shown = (hit.value or hit.name)[:80]
            found.append(f"id {window['id']}  {window['app']}  \"{window['title']}\"  (shows: {shown})")
    return "\n".join(found) or f"No open window shows '{wanted}'."


def workspace_tools() -> list[Tool]:
    return [
        Tool("list_workspaces", "Virtual desktops and activities, and which are current.", object_schema(),
             RISK_READ, list_workspaces, summarize=lambda a: "List desktops and activities"),
        Tool("desktop_action", "Switch to, create, rename or remove a virtual desktop.",
             object_schema({"action": {"type": "string", "enum": ["switch", "create", "rename", "remove"]},
                            "desktop": {"type": "string", "description": "Its number or name"},
                            "name": {"type": "string", "description": "New name"}}, ["action"]),
             RISK_CHANGE, desktop_action, summarize=lambda a: f"Virtual desktop: {a.get('action', '?')} {a.get('desktop') or a.get('name') or ''}"),
        Tool("activity_action", "Switch to or create a Plasma activity.",
             object_schema({"action": {"type": "string", "enum": ["switch", "create"]}, "name": {"type": "string"}},
                           ["action", "name"]), RISK_CHANGE, activity_action,
             summarize=lambda a: f"Activity: {a.get('action', '?')} {a.get('name', '')}"),
        Tool("find_window_with_text", "Find the open window that shows some text (in its title or its "
             "contents), for example 'the window with the invoice'.", object_schema({"text": {"type": "string"}}, ["text"]),
             RISK_READ, find_window_with_text, summarize=lambda a: f"Look for the window showing '{a.get('text', '?')}'"),
        Tool("show_desktop", "Minimise everything to show the desktop, or bring the windows back.",
             object_schema({"show": {"type": "boolean"}}), RISK_CHANGE, show_desktop,
             summarize=lambda a: "Show the desktop" if a.get("show", True) else "Bring the windows back"),
        Tool("close_other_windows", "Close every window except those of the named applications.",
             object_schema({"keep": {"type": "array", "items": {"type": "string"}}}, ["keep"]), RISK_CHANGE,
             close_other_windows, summarize=lambda a: f"Close all windows except {', '.join(a.get('keep') or []) or 'none'}"),
    ]
