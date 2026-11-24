"""Screen and clipboard tools: clipboard history, selected text, screenshots, recording, colour picker.

- Clipboard history comes from Klipper over DBus (``getClipboardHistoryItem``),
  the history the clipboard applet shows.
- Selected text is the Wayland primary selection (``wl-paste --primary``):
  whatever the user last highlighted in any application, so "explain the
  selected text" works without copying first. It is a ``private`` tool: its
  result reaches an online AI only when the user's ``app_context`` setting
  allows it (``app_context``).
- Screenshots are taken with Spectacle in background mode into the user's
  Pictures/Screenshots folder (a region screenshot lets the user drag the
  area). The returned path can be passed to ``text_from_image``
  (``tools/documents.py``) to read its text, which works on text-only models.
- Recording opens Spectacle's own recorder for the chosen area; the user
  stops it from Spectacle's indicator, so nothing records unseen.
- The colour picker is KWin's (``org.kde.KWin /ColorPicker``): the user
  clicks a point and gets its colour as ``#rrggbb``.

Reading is ``read``; taking a screenshot, starting a recording and picking a
colour are ``change`` (they create a file or wait for a click).
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .. import session_dbus
from ..desktop_context import run_command
from .power import run_checked
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

MAX_HISTORY = 20


def clipboard_history(arguments: dict[str, Any]) -> str:
    limit = arguments.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY:
        raise ToolFailure(f"'limit' must be a whole number from 1 to {MAX_HISTORY}")
    items = []
    for index in range(limit):
        try:
            item = session_dbus.call("org.kde.klipper", "/klipper", "org.kde.klipper.klipper",
                                     "getClipboardHistoryItem", "i", (index,))[0]
        except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
            raise ToolFailure(f"the clipboard history is not available ({error})") from error
        if not item:
            break
        items.append(f"{index + 1}. {item[:500]}")
    return "\n".join(items) or "The clipboard history is empty."


def selected_text(arguments: dict[str, Any]) -> str:
    if not shutil.which("wl-paste"):
        raise ToolFailure("wl-paste is not installed")
    result = run_command(["wl-paste", "--primary", "--no-newline"], timeout=5)
    text = result["stdout"] if result["ok"] else ""
    return text[:20000] if text.strip() else "No text is selected right now."


def _screenshot_folder() -> Path:
    from ..agent_loop import user_folders

    folder = Path(user_folders().get("Pictures", str(Path.home() / "Pictures"))) / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def take_screenshot(arguments: dict[str, Any]) -> str:
    area = arguments.get("area", "screen")
    flags = {"screen": "-f", "window": "-a", "region": "-r"}
    if area not in flags:
        raise ToolFailure("'area' must be screen, window or region")
    target = _screenshot_folder() / f"Screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    run_checked(["spectacle", "-b", "-n", flags[area], "-o", str(target)], timeout=120)
    if not target.exists():
        raise ToolFailure("no screenshot was taken (the selection may have been cancelled)")
    return f"Saved the screenshot as {target}. To read its text, use text_from_image."


def record_screen(arguments: dict[str, Any]) -> str:
    area = arguments.get("area", "region")
    if area not in ("screen", "window", "region"):
        raise ToolFailure("'area' must be screen, window or region")
    if not shutil.which("spectacle"):
        raise ToolFailure("Spectacle is not installed")
    subprocess.Popen(["spectacle", "--record", area[0]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return ("Opened Spectacle's screen recorder" + (" — drag the area to record" if area == "region" else "")
            + ". Stop it from Spectacle's indicator in the panel; it saves the video in Videos.")


def pick_color(arguments: dict[str, Any]) -> str:
    try:
        value = session_dbus.call("org.kde.KWin", "/ColorPicker", "org.kde.kwin.ColorPicker", "pick")[0]
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"the colour picker did not return a colour ({error})") from error
    value = value[0] if isinstance(value, tuple) else value
    return f"#{value & 0xFFFFFF:06x}"


def screen_tools() -> list[Tool]:
    area = {"type": "string", "enum": ["screen", "window", "region"]}
    return [
        Tool("clipboard_history", "Earlier clipboard entries, newest first.",
             object_schema({"limit": {"type": "integer", "description": f"Default 10, max {MAX_HISTORY}"}}),
             RISK_READ, clipboard_history, summarize=lambda a: "Read the clipboard history"),
        Tool("selected_text", "The text the user has highlighted (selected) in any application right now.",
             object_schema(), RISK_READ, selected_text, summarize=lambda a: "Read the selected text", private=True),
        Tool("take_screenshot", "Take a screenshot of the whole screen, the active window, or an area the user "
             "drags, saved in Pictures/Screenshots. Pass the file to text_from_image to read text from it.",
             object_schema({"area": area}), RISK_CHANGE, take_screenshot,
             summarize=lambda a: f"Take a screenshot ({a.get('area', 'screen')})"),
        Tool("record_screen", "Open the screen recorder for the screen, a window or an area; the user stops it.",
             object_schema({"area": area}), RISK_CHANGE, record_screen,
             summarize=lambda a: f"Record the {a.get('area', 'region')}"),
        Tool("pick_color", "Let the user click anywhere on screen and return that point's colour as #rrggbb.",
             object_schema(), RISK_CHANGE, pick_color, summarize=lambda a: "Pick a colour from the screen"),
    ]
