"""Appearance and input tools: wallpaper, accent colour, cursor, Plasma and icon themes, keyboard layout.

Each uses the program Plasma ships for the job, the same ones its settings
pages call: ``plasma-apply-wallpaperimage``, ``plasma-apply-colorscheme
--accent-color``, ``plasma-apply-cursortheme``, ``plasma-apply-desktoptheme``
and ``plasma-changeicons`` (in ``/usr/lib``). The current wallpaper is read
through the Plasma shell's scripting interface so a change can be undone;
the keyboard layout goes through ``org.kde.keyboard`` on the session DBus.

Wallpaper and the cursor and Plasma themes record their previous value in
``undo_journal`` (kinds ``wallpaper`` and ``theme``). Everything that
changes is ``change``; the lists are ``read``.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import Any

from .. import session_dbus, undo_journal
from ..desktop_context import run_command
from .power import run_checked
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

ICON_CHANGER_PATHS = ("/usr/lib/plasma-changeicons", "/usr/libexec/plasma-changeicons")
_WALLPAPER_SCRIPT = ('var d = desktops()[0]; d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"]; '
                     'print(d.readConfig("Image"));')
_THEME_COMMANDS = {"cursor": "plasma-apply-cursortheme", "plasma": "plasma-apply-desktoptheme"}


def current_wallpaper() -> str:
    result = run_command(["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                          _WALLPAPER_SCRIPT], timeout=5) if shutil.which("qdbus6") else {"ok": False}
    return result["stdout"].strip().removeprefix("file://") if result["ok"] else ""


def set_wallpaper(arguments: dict[str, Any]) -> str:
    image = os.path.abspath(os.path.expanduser(str(arguments.get("image") or "").strip()))
    if not os.path.isfile(image):
        raise ToolFailure(f"{image} is not an image file that exists")
    previous = current_wallpaper()
    run_checked(["plasma-apply-wallpaperimage", image])
    if previous and os.path.isfile(previous):
        undo_journal.record("wallpaper", "Changed the wallpaper", {"image": previous})
    return f"Wallpaper set to {image}."


def set_accent_color(arguments: dict[str, Any]) -> str:
    color = str(arguments.get("color") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}|[a-zA-Z]{3,20}", color):
        raise ToolFailure("'color' must be a colour such as #3daee9 or a name such as orange")
    run_checked(["plasma-apply-colorscheme", "--accent-color", color])
    return f"Accent colour set to {color}."


def _themes(kind: str) -> tuple[list[tuple[str, str]], str]:
    """``([(label, id)], current id)`` from a plasma-apply-* --list-themes listing."""
    themes, current = [], ""
    for line in run_checked([_THEME_COMMANDS[kind], "--list-themes"]).splitlines():
        match = re.match(r"^\s*\*\s+(.+?)(?:\s+\[([^\]]+)\])?\s*(\((?i:current).*\))?$", line)
        if match:
            label, ident = match.group(1).strip(), (match.group(2) or match.group(1)).strip()
            themes.append((label, ident))
            if match.group(3):
                current = ident
    return themes, current


def list_themes(arguments: dict[str, Any]) -> str:
    lines = []
    for kind in ("cursor", "plasma"):
        themes, current = _themes(kind)
        lines.append(f"{kind.capitalize()} themes: " + ", ".join(
            f"{label}{' (current)' if ident == current else ''}" for label, ident in themes))
    return "\n".join(lines)


def set_theme(arguments: dict[str, Any]) -> str:
    kind, wanted = arguments.get("kind"), str(arguments.get("name") or "").strip().lower()
    if kind == "icons":
        changer = next((path for path in ICON_CHANGER_PATHS if os.path.exists(path)), "")
        if not changer:
            raise ToolFailure("plasma-changeicons is not installed")
        run_checked([changer, str(arguments.get("name") or "").strip()])
        return f"Icon theme set to {arguments.get('name')}."
    if kind not in _THEME_COMMANDS:
        raise ToolFailure("'kind' must be cursor, plasma or icons")
    themes, current = _themes(kind)
    match = [ident for label, ident in themes if wanted in (label.lower(), ident.lower())]
    if not match:
        raise ToolFailure(f"no {kind} theme named '{wanted}'. Installed: {', '.join(label for label, _ in themes)}")
    run_checked([_THEME_COMMANDS[kind], match[0]])
    if current and current != match[0]:
        undo_journal.record("theme", f"Changed the {kind} theme from {current}", {"kind": kind, "name": current})
    return f"The {kind} theme is now {match[0]}."


def _layouts() -> tuple[list[tuple[str, str, str]], int]:
    try:
        layouts = session_dbus.call("org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts", "getLayoutsList")[0]
        current = session_dbus.call("org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts", "getLayout")[0]
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"keyboard layouts are not available ({error})") from error
    return list(layouts), current


def keyboard_layouts(arguments: dict[str, Any]) -> str:
    layouts, current = _layouts()
    return "Keyboard layouts: " + ", ".join(
        f"{name} [{short}{'-' + variant if variant else ''}]{' (current)' if index == current else ''}"
        for index, (short, variant, name) in enumerate(layouts))


def set_keyboard_layout(arguments: dict[str, Any]) -> str:
    wanted = str(arguments.get("layout") or "").strip().lower()
    layouts, _ = _layouts()
    for index, (short, variant, name) in enumerate(layouts):
        if wanted in (short.lower(), name.lower(), f"{short}-{variant}".lower()):
            session_dbus.call("org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts", "setLayout", "u", (index,))
            return f"Keyboard layout switched to {name}."
    raise ToolFailure(f"'{wanted}' is not one of the configured layouts. {keyboard_layouts({})}. Others are added "
                      "in System Settings, Keyboard.")


def appearance_tools() -> list[Tool]:
    return [
        Tool("set_wallpaper", "Set the desktop wallpaper to an image file.",
             object_schema({"image": {"type": "string"}}, ["image"]), RISK_CHANGE, set_wallpaper,
             summarize=lambda a: f"Set the wallpaper to {a.get('image', '?')}"),
        Tool("set_accent_color", "Set the accent colour used for highlights.",
             object_schema({"color": {"type": "string", "description": "#rrggbb or a colour name"}}, ["color"]),
             RISK_CHANGE, set_accent_color, summarize=lambda a: f"Set the accent colour to {a.get('color', '?')}"),
        Tool("list_themes", "The installed cursor and Plasma themes and which are in use.", object_schema(),
             RISK_READ, list_themes, summarize=lambda a: "List themes"),
        Tool("set_theme", "Switch the cursor theme, the Plasma (panel and widget) theme, or the icon theme.",
             object_schema({"kind": {"type": "string", "enum": ["cursor", "plasma", "icons"]},
                            "name": {"type": "string"}}, ["kind", "name"]), RISK_CHANGE, set_theme,
             summarize=lambda a: f"Switch the {a.get('kind', '?')} theme to {a.get('name', '?')}"),
        Tool("keyboard_layouts", "The configured keyboard layouts and which one is active.", object_schema(),
             RISK_READ, keyboard_layouts, summarize=lambda a: "List keyboard layouts"),
        Tool("set_keyboard_layout", "Switch to one of the configured keyboard layouts.",
             object_schema({"layout": {"type": "string", "description": "Its name or short code, e.g. de"}},
                           ["layout"]), RISK_CHANGE, set_keyboard_layout,
             summarize=lambda a: f"Switch the keyboard to {a.get('layout', '?')}"),
    ]
