"""GUI control tools: read another application's interface, press its controls, type.

These let a model that cannot see the screen operate an application the way
a person would. ``ui_snapshot`` lists a window's controls with short refs
(``accessibility``); ``ui_press``, ``ui_set_text`` and ``ui_get_text`` act on
one control, named by ref or by its label; ``press_keys`` and ``type_text``
send keyboard input through the desktop portal (``input_portal``).

Every tool takes an optional ``window`` (``current`` by default, see
``tools.windows``). Key input goes to whatever has focus, and while the user
types a request the focus is on the panel bar, so the key tools first focus
the target window.

Risk. Operating a GUI is ``change`` in general, but the same click can
delete something, so each call is classified on what can be known:

- ``ui_press`` is ``danger`` when the control's label says it deletes,
  discards, formats, uninstalls or ends the session (``DANGER_LABEL``).
- ``press_keys`` is ``danger`` for Delete combinations, and for Enter while a
  terminal is focused, because that runs whatever is on its command line.
- ``type_text`` into a terminal is classified as the shell command it types.

This is best-effort: a harmless-looking button can still be destructive.

Privacy. ``ui_snapshot`` and ``ui_get_text`` read what is inside the user's
applications, so they are ``private`` tools: their results reach an online AI
only when the user's ``app_context`` setting allows it (``app_context``).

Refs belong to the most recent ``ui_snapshot`` of that application; after an
action changes the interface, the model must take a new snapshot. Titles
change while an application is used, so results always give the window's
stable id, and ``ui_press`` reports windows of the application that opened,
closed or were retitled as a result (a Save dialog, for example).
"""

from __future__ import annotations

import re
import time
from typing import Any

from .. import accessibility, input_portal, kwin_bridge
from ..shell_risk import classify_command
from . import windows
from .registry import RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, object_schema

MAX_LISTED = 150
MAX_QUERY_MATCHES = 60
DANGER_LABEL = re.compile(
    r"\b(delete|remove|erase|discard|empty (the )?(trash|wastebin|bin)|format|uninstall|wipe|purge|overwrite|replace|"
    r"shut ?down|restart|reboot|log ?out|sign out|don'?t save|close without saving|reset|clear (all|history)|"
    r"move to (trash|wastebin))\b", re.IGNORECASE)
TERMINAL_APPLICATIONS = ("konsole", "yakuake", "kitty", "alacritty", "foot", "wezterm", "gnome-terminal", "xterm",
                         "terminator", "tilix", "ghostty", "ptyxis", "kgx")
FOCUS_SETTLE_SECONDS = 0.25
PRESS_SETTLE_SECONDS = 0.6


def _target(arguments: dict[str, Any]) -> dict[str, Any]:
    """The window the call is about, as described by KWin (id, title, app, pid)."""
    return windows.describe_window(arguments.get("window") or "current")


def _is_terminal(window: dict[str, Any]) -> bool:
    return any(name in str(window.get("app", "")).lower() for name in TERMINAL_APPLICATIONS)


def _snapshot(window: dict[str, Any]) -> accessibility.Snapshot:
    try:
        return accessibility.take_snapshot(int(window["pid"]), window["title"])
    except accessibility.AccessibilityUnavailable as error:
        raise ToolFailure(str(error)) from error


def _resolve(arguments: dict[str, Any], actionable: bool) -> tuple[dict[str, Any], accessibility.Element]:
    """Find the element named by ``arguments['element']``: a ref from the last snapshot, or a label."""
    wanted = arguments.get("element")
    if not isinstance(wanted, str) or not wanted.strip():
        raise ToolFailure("'element' is required: a ref such as e12 from ui_snapshot, or the control's label")
    wanted = wanted.strip()
    window = _target(arguments)
    if accessibility.REF_PATTERN.match(wanted):
        snapshot = accessibility.last_snapshot(int(window["pid"]))
        element = snapshot.by_ref(wanted) if snapshot else None
        if element is None:
            raise ToolFailure(f"{wanted} is not from a current snapshot of this window. Call ui_snapshot again.")
        return window, element
    matches = accessibility.find_elements(_snapshot(window), wanted, actionable_only=actionable)
    if not matches:
        raise ToolFailure(f"no control labelled '{wanted}' in \"{window['title']}\". Call ui_snapshot to see what is there.")
    if len(matches) > 1:
        options = "\n".join(match.line().strip() for match in matches[:12])
        raise ToolFailure(f"{len(matches)} controls match '{wanted}'. Use a ref:\n{options}")
    return window, matches[0]


def _guard(action, element: accessibility.Element):
    try:
        return action()
    except accessibility.ElementGone:
        raise ToolFailure(
            f"{element.ref} is no longer part of the window (the interface changed). Call ui_snapshot again.") from None
    except accessibility.AccessibilityUnavailable as error:
        raise ToolFailure(str(error)) from error


def ui_snapshot(arguments: dict[str, Any]) -> str:
    window = _target(arguments)
    snapshot = _snapshot(window)
    query = str(arguments.get("query") or "").strip()
    if query:
        chosen = accessibility.find_elements(snapshot, query)[:MAX_QUERY_MATCHES]
        note = f"{len(chosen)} control(s) matching '{query}'"
    else:
        chosen = [element for element in snapshot.elements if element.showing][:MAX_LISTED]
        hidden = sum(1 for element in snapshot.elements if not element.showing)
        note = f"{len(chosen)} visible control(s)"
        if hidden:
            note += f"; {hidden} more are not on screen (mostly menu entries). Pass query to find one, e.g. query='save'"
    lines = [f"Window \"{snapshot.title}\" ({snapshot.application}), id {window['id']}: {note}."]
    lines += [element.line() for element in chosen]
    if snapshot.truncated:
        lines.append("[the window has more controls than could be read]")
    if not chosen:
        lines.append("(nothing to list)")
    return "\n".join(lines)


def classify_press(arguments: dict[str, Any]) -> tuple[str, str]:
    try:
        _window, element = _resolve(arguments, actionable=True)
    except ToolFailure:
        return RISK_CHANGE, ""
    if DANGER_LABEL.search(element.name):
        return RISK_DANGER, f"the control is labelled \"{element.name}\""
    return RISK_CHANGE, ""


def _window_changes(pid: int, before: list[dict[str, Any]]) -> str:
    """Describe which of a process's windows opened, closed or were retitled since ``before``."""
    old = {window["id"]: window["title"] for window in before}
    new = {window["id"]: window["title"] for window in windows.windows_of_process(pid)}
    notes = [f"Opened window \"{title}\", id {key}." for key, title in new.items() if key not in old]
    notes += [f"Closed window \"{title}\"." for key, title in old.items() if key not in new]
    notes += [f"Window id {key} is now titled \"{title}\"." for key, title in new.items()
              if key in old and old[key] != title]
    return " ".join(notes)


def ui_press(arguments: dict[str, Any]) -> str:
    window, element = _resolve(arguments, actionable=True)
    pid = int(window["pid"])
    before = windows.windows_of_process(pid)
    outcome = _guard(lambda: accessibility.press(element), element)
    time.sleep(PRESS_SETTLE_SECONDS)
    changes = _window_changes(pid, before)
    return (f"{element.role} \"{element.name}\": {outcome}. " + (changes or "No window opened or closed.")
            + " Call ui_snapshot on the window you need next.")


def ui_set_text(arguments: dict[str, Any]) -> str:
    text = arguments.get("text")
    if not isinstance(text, str):
        raise ToolFailure("'text' is required")
    window, element = _resolve(arguments, actionable=True)
    _guard(lambda: accessibility.set_text(element, text), element)
    return f"Set {element.ref} ({element.role}) in window id {window['id']} to {len(text)} characters of text."


def ui_get_text(arguments: dict[str, Any]) -> str:
    _window, element = _resolve(arguments, actionable=False)
    return _guard(lambda: accessibility.get_text(element, 6000), element) or "(empty)"


def _focus_target(arguments: dict[str, Any]) -> dict[str, Any]:
    window = _target(arguments)
    if not window.get("active"):
        windows.focus_window({"window": window["id"]})
        time.sleep(FOCUS_SETTLE_SECONDS)
    return window


def _key_list(arguments: dict[str, Any]) -> list[str]:
    keys = arguments.get("keys")
    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key.strip() for key in keys):
        raise ToolFailure("'keys' is required: one combination such as 'ctrl+s', or a list of them")
    return keys


def classify_keys(arguments: dict[str, Any]) -> tuple[str, str]:
    try:
        keys = [key.lower().replace(" ", "") for key in _key_list(arguments)]
        window = _target(arguments)
    except ToolFailure:
        return RISK_CHANGE, ""
    for key in keys:
        if key.split("+")[-1] in ("delete", "del") and key != "delete" and key != "del":
            return RISK_DANGER, f"{key} usually deletes without a way back"
        if key.split("+")[-1] in ("return", "enter") and _is_terminal(window):
            return RISK_DANGER, "Enter in a terminal runs whatever is on its command line"
    return RISK_CHANGE, ""


def press_keys(arguments: dict[str, Any]) -> str:
    keys = _key_list(arguments)
    window = _focus_target(arguments)
    try:
        for key in keys:
            input_portal.shared().press_keys(key)
            time.sleep(0.05)
    except input_portal.InputUnavailable as error:
        raise ToolFailure(str(error)) from error
    return f"Pressed {', '.join(keys)} in \"{window['title']}\" (id {window['id']})."


def classify_type(arguments: dict[str, Any]) -> tuple[str, str]:
    text = arguments.get("text")
    try:
        window = _target(arguments)
    except ToolFailure:
        return RISK_CHANGE, ""
    if isinstance(text, str) and _is_terminal(window):
        risk, reason = classify_command(text)
        if risk == RISK_DANGER:
            return RISK_DANGER, f"types a terminal command that {reason}"
        if "\n" in text:
            return RISK_DANGER, "types into a terminal and presses Enter, which runs it"
    return RISK_CHANGE, ""


def type_text(arguments: dict[str, Any]) -> str:
    text = arguments.get("text")
    if not isinstance(text, str) or not text:
        raise ToolFailure("'text' is required")
    if len(text) > 5000:
        raise ToolFailure("that is too much to type; write a file or set the clipboard instead")
    window = _focus_target(arguments)
    try:
        input_portal.shared().type_text(text)
    except input_portal.InputUnavailable as error:
        raise ToolFailure(str(error)) from error
    return f"Typed {len(text)} characters into \"{window['title']}\"."


def gui_tools() -> list[Tool]:
    window = {"type": "string", "description": "'current' (default), a window id, or part of an app name or title"}
    element = {"type": "string", "description": "A ref such as e12 from ui_snapshot, or the control's visible label"}
    return [
        Tool("ui_snapshot", "List the controls of an application window (buttons, menus, text fields, tabs, list "
             "items) with a ref for each. Use this before pressing or typing, and again after the window changes.",
             object_schema({"window": window, "query": {
                 "type": "string", "description": "Only controls whose label matches, including ones not on screen"}}),
             RISK_READ, ui_snapshot, private=True),
        Tool("ui_press", "Press a button, menu entry, tab, link, check box or list item in a window.",
             object_schema({"element": element, "window": window}, ["element"]), RISK_CHANGE, ui_press,
             classify=classify_press, summarize=lambda a: f"Press \"{a.get('element', '')}\""),
        Tool("ui_set_text", "Replace the contents of a text field or editor in a window.",
             object_schema({"element": element, "text": {"type": "string"}, "window": window}, ["element", "text"]),
             RISK_CHANGE, ui_set_text,
             summarize=lambda a: f"Set text of \"{a.get('element', '')}\" ({len(str(a.get('text', '')))} characters)"),
        Tool("ui_get_text", "Read the full text of a field, editor, label or other control.",
             object_schema({"element": element, "window": window}, ["element"]), RISK_READ, ui_get_text, private=True),
        Tool("press_keys", "Press keys in a window, as on the keyboard: a shortcut such as 'ctrl+s', or 'Return', "
             "'Tab', 'Escape', 'alt+F4'. Several are pressed in order.",
             object_schema({"keys": {"type": "array", "items": {"type": "string"}}, "window": window}, ["keys"]),
             RISK_CHANGE, press_keys, classify=classify_keys, summarize=lambda a: f"Press keys {a.get('keys', '')}"),
        Tool("type_text", "Type text at the cursor of a window, as on the keyboard. Prefer ui_set_text for a field "
             "you can name; use this when a control accepts only real typing.",
             object_schema({"text": {"type": "string"}, "window": window}, ["text"]), RISK_CHANGE, type_text,
             classify=classify_type, summarize=lambda a: f"Type {len(str(a.get('text', '')))} characters"),
    ]
