"""Window management tools: focus, close, place and resize application windows.

All of them act through ``kwin_bridge`` by running a small script inside
KWin, which is the only interface KWin offers for this on Wayland. Every tool
has risk ``change``: the effect is visible and reversible. Closing a window
asks the application to close, so an application with unsaved work shows its
own prompt.

Windows are addressed by the ``window`` argument: an id from
``list_windows``, text matched case-insensitively against the application
name and the title, or ``current`` (also the default) for the window the
user is working in. Text must match exactly one window; when it
matches none or several the tool fails and lists the candidates with their
ids, so the model can retry precisely.

Layouts are computed from the screen's usable area (panels excluded) of the
screen the window is on, or of the named ``screen``.

Before a window is placed, resized or changed in state, its current place
is recorded in ``undo_journal`` so the change can be undone
(``tools/undo.py``).
"""

from __future__ import annotations

import json
from typing import Any

from .. import kwin_bridge, undo_journal
from .registry import RISK_CHANGE, Tool, ToolFailure, object_schema

LAYOUTS = ("left", "right", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right",
           "maximize", "center", "restore")

_FIND_JS = kwin_bridge.WINDOW_FIELDS_JS + kwin_bridge.CURRENT_WINDOW_JS + """
function find(query) {
    var all = workspace.windowList().filter(function (w) { return w.normalWindow; });
    // Ids are accepted with or without their surrounding braces.
    var bare = String(query).replace(/[{}]/g, "").toLowerCase();
    var byId = all.filter(function (w) { return String(w.internalId).replace(/[{}]/g, "").toLowerCase() === bare; });
    if (byId.length) { return byId; }
    var text = String(query).toLowerCase();
    var exactApp = all.filter(function (w) { return String(w.resourceClass).toLowerCase() === text; });
    if (exactApp.length === 1) { return exactApp; }
    return all.filter(function (w) {
        return String(w.resourceClass).toLowerCase().indexOf(text) >= 0
            || String(w.caption).toLowerCase().indexOf(text) >= 0;
    });
}
// Dialogs are not "normal" windows, so ids are also looked up among all windows.
function findAny(query) {
    var bare = String(query).replace(/[{}]/g, "").toLowerCase();
    var byId = workspace.windowList().filter(function (w) {
        return String(w.internalId).replace(/[{}]/g, "").toLowerCase() === bare;
    });
    return byId.length ? byId : find(query);
}
// KWin applies geometry changes after the script returns, so replies report
// the geometry that was requested rather than reading it back.
function placed(w, g) {
    var info = describe(w);
    info.x = Math.round(g.x); info.y = Math.round(g.y);
    info.width = Math.round(g.width); info.height = Math.round(g.height);
    return { window: info };
}
var args = %s;
var found = (args.window === "" || args.window === "current")
    ? (currentWindow() ? [currentWindow()] : []) : findAny(args.window);
if (found.length !== 1) {
    return { matched: found.length, candidates: (found.length ? found : workspace.windowList().filter(
        function (w) { return w.normalWindow; })).map(describe) };
}
var w = found[0];
"""

_ARRANGE_JS = """
var output = w.output;
if (args.screen) {
    var screens = workspace.screens.filter(function (s) { return s.name === args.screen; });
    if (!screens.length) { return { error: "no screen named " + args.screen, screens: workspace.screens.map(
        function (s) { return s.name; }) }; }
    output = screens[0];
}
var area = workspace.clientArea(KWin.MaximizeArea, output, workspace.currentDesktop);
if (w.fullScreen) { w.fullScreen = false; }
if (args.layout === "maximize") { w.setMaximize(true, true); return placed(w, area); }
w.setMaximize(false, false);
if (args.layout === "restore") { return { window: describe(w) }; }
var halfW = Math.floor(area.width / 2), halfH = Math.floor(area.height / 2);
var g = { x: area.x, y: area.y, width: area.width, height: area.height };
if (args.layout.indexOf("left") >= 0) { g.width = halfW; }
if (args.layout.indexOf("right") >= 0) { g.x = area.x + halfW; g.width = area.width - halfW; }
if (args.layout.indexOf("top") >= 0) { g.height = halfH; }
if (args.layout.indexOf("bottom") >= 0) { g.y = area.y + halfH; g.height = area.height - halfH; }
if (args.layout === "center") {
    g.width = Math.floor(area.width * 0.6); g.height = Math.floor(area.height * 0.7);
    g.x = area.x + Math.floor((area.width - g.width) / 2); g.y = area.y + Math.floor((area.height - g.height) / 2);
}
w.minimized = false;
w.frameGeometry = g;
return placed(w, g);
"""

_GEOMETRY_JS = """
if (w.fullScreen) { w.fullScreen = false; }
w.setMaximize(false, false);
var g = w.frameGeometry;
var target = {
    x: args.x === null ? g.x : args.x, y: args.y === null ? g.y : args.y,
    width: args.width === null ? g.width : args.width, height: args.height === null ? g.height : args.height
};
w.frameGeometry = target;
return placed(w, target);
"""

_STATE_JS = """
if (args.minimized !== null) { w.minimized = args.minimized; }
if (args.fullscreen !== null) { w.fullScreen = args.fullscreen; }
if (args.keep_above !== null) { w.keepAbove = args.keep_above; }
if (args.desktop !== null) {
    var desktops = workspace.desktops;
    if (args.desktop < 1 || args.desktop > desktops.length) {
        return { error: "there are " + desktops.length + " virtual desktops" };
    }
    w.desktops = [desktops[args.desktop - 1]];
}
return { window: describe(w) };
"""


def _describe(window: dict[str, Any]) -> str:
    return (f"id {window['id']}  {window['app']}  \"{window['title']}\"  "
            f"{window['width']}x{window['height']} at {window['x']},{window['y']} on {window['screen']}")


def _run(arguments: dict[str, Any], action_js: str) -> dict[str, Any]:
    """Find the one window ``arguments['window']`` names and run ``action_js`` on it."""
    target = arguments.get("window", "current")
    if not isinstance(target, str) or not target.strip():
        target = "current"
    payload = {**arguments, "window": target.strip()}
    try:
        result = kwin_bridge.shared().run(_FIND_JS % json.dumps(payload) + action_js)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError) as error:
        raise ToolFailure(str(error)) from error
    if "matched" in result:
        listing = "\n".join(_describe(window) for window in result["candidates"]) or "(no windows are open)"
        problem = "no window matches" if result["matched"] == 0 else f"{result['matched']} windows match"
        raise ToolFailure(f"{problem} '{target}'. Use an id from this list:\n{listing}")
    if result.get("error"):
        extra = f" Screens: {', '.join(result['screens'])}." if result.get("screens") else ""
        raise ToolFailure(result["error"] + extra)
    return result


def _optional_int(arguments: dict[str, Any], name: str) -> int | None:
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolFailure(f"'{name}' must be a number")
    return int(value)


def _optional_bool(arguments: dict[str, Any], name: str) -> bool | None:
    value = arguments.get(name)
    if value is None or isinstance(value, bool):
        return value
    raise ToolFailure(f"'{name}' must be true or false")


def windows_of_process(pid: int) -> list[dict[str, Any]]:
    """Every window (dialogs included) that belongs to process ``pid``."""
    script = kwin_bridge.WINDOW_FIELDS_JS + (
        "return workspace.windowList().filter(function (w) { return w.pid === %d && !w.deleted; }).map(describe);" % pid)
    try:
        return kwin_bridge.shared().run(script)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError):
        return []


def describe_window(window: str) -> dict[str, Any]:
    """KWin's description (id, title, app, pid, geometry, active) of the one window ``window`` names."""
    return _run({"window": window}, "return { window: describe(w) };")["window"]


def _remember_place(arguments: dict[str, Any], verb: str) -> None:
    """Record where the window is now, so the change about to be made can be undone."""
    try:
        before = describe_window(str(arguments.get("window") or "current"))
    except ToolFailure:
        return
    undo_journal.record("window", f"{verb} window {before['app']} \"{before['title']}\"", {
        "window": before["id"], **{name: before[name] for name in ("x", "y", "width", "height", "minimized", "fullscreen")}})


def focus_window(arguments: dict[str, Any]) -> str:
    result = _run(arguments, "w.minimized = false; workspace.activeWindow = w; return { window: describe(w) };")
    return "Focused: " + _describe(result["window"])


def close_window(arguments: dict[str, Any]) -> str:
    result = _run(arguments, "var info = describe(w); w.closeWindow(); return { window: info };")
    return "Asked to close: " + _describe(result["window"])


def arrange_window(arguments: dict[str, Any]) -> str:
    layout = arguments.get("layout")
    if layout not in LAYOUTS:
        raise ToolFailure(f"'layout' must be one of: {', '.join(LAYOUTS)}")
    screen = arguments.get("screen")
    _remember_place(arguments, "Arranged")
    result = _run({"window": arguments.get("window"), "layout": layout, "screen": screen or None}, _ARRANGE_JS)
    return f"Placed {layout}: " + _describe(result["window"])


def move_resize_window(arguments: dict[str, Any]) -> str:
    geometry = {name: _optional_int(arguments, name) for name in ("x", "y", "width", "height")}
    if all(value is None for value in geometry.values()):
        raise ToolFailure("give at least one of x, y, width, height")
    for name in ("width", "height"):
        if geometry[name] is not None and geometry[name] < 50:
            raise ToolFailure(f"'{name}' must be at least 50 pixels")
    _remember_place(arguments, "Moved")
    result = _run({"window": arguments.get("window"), **geometry}, _GEOMETRY_JS)
    return "Now: " + _describe(result["window"])


def set_window_state(arguments: dict[str, Any]) -> str:
    state = {name: _optional_bool(arguments, name) for name in ("minimized", "fullscreen", "keep_above")}
    desktop = _optional_int(arguments, "desktop")
    if desktop is None and all(value is None for value in state.values()):
        raise ToolFailure("give at least one of minimized, fullscreen, keep_above, desktop")
    _remember_place(arguments, "Changed")
    result = _run({"window": arguments.get("window"), **state, "desktop": desktop}, _STATE_JS)
    return "Now: " + _describe(result["window"])


def window_tools() -> list[Tool]:
    window = {"type": "string", "description": "'current' (default) for the window the user is working in, a window "
              "id from list_windows, or part of the application name or title"}

    def tool(name: str, description: str, properties: dict[str, Any], handler, verb: str) -> Tool:
        return Tool(name, description, object_schema({"window": window, **properties},
                                                       ["layout"] if name == "arrange_window" else []), RISK_CHANGE, handler,
            summarize=lambda arguments: f"{verb} window '{arguments.get('window') or 'current'}'")

    return [
        tool("focus_window", "Bring a window to the front and give it keyboard focus.", {}, focus_window, "Focus"),
        tool("close_window", "Ask a window to close, as if its close button were clicked.", {}, close_window, "Close"),
        tool("arrange_window", "Place a window in a standard position on its screen: a half, a quarter, maximized, "
             "centered, or restored. To put two windows side by side, call this once for each.",
             {"layout": {"type": "string", "enum": list(LAYOUTS)},
              "screen": {"type": "string", "description": "Screen name from list_windows; default is the window's own"}},
             arrange_window, "Arrange"),
        tool("move_resize_window", "Set a window's exact position and size in pixels. Omitted values stay as they are.",
             {name: {"type": "integer"} for name in ("x", "y", "width", "height")}, move_resize_window, "Move"),
        tool("set_window_state", "Minimize or restore a window, toggle fullscreen or keep-above, or send it to a "
             "virtual desktop (numbered from 1).",
             {"minimized": {"type": "boolean"}, "fullscreen": {"type": "boolean"}, "keep_above": {"type": "boolean"},
              "desktop": {"type": "integer"}}, set_window_state, "Change"),
    ]
