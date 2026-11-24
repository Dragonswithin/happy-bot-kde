"""Appearance and input tools: wallpaper, accent colour, cursor, Plasma and icon themes, keyboard layout.

Each uses the program Plasma ships for the job, the same ones its settings
pages call: ``plasma-apply-wallpaperimage``, ``plasma-apply-colorscheme
--accent-color``, ``plasma-apply-cursortheme``, ``plasma-apply-desktoptheme``
and ``plasma-changeicons`` (in ``/usr/lib``). A wallpaper slideshow has no
such program, so ``apply_slideshow`` switches every desktop to Plasma's
``org.kde.slideshow`` wallpaper through the Plasma shell's scripting
interface (``evaluateScript``), as the desktop's own settings do; it applies
at once, with no shell restart. The wallpaper in use (one image, or a
slideshow's folders and interval) is read the same way, so a change can be
undone and so ``set_wallpaper`` can check that the change really took before
saying so. The keyboard layout goes through ``org.kde.keyboard`` on the
session DBus.

Mice and touchpads (speed, natural scrolling, tap to click) are KWin's
input devices on DBus (``/org/kde/KWin/InputDevice``), changed live as the
Mouse and Touchpad pages do; key repeat is written to ``kcminputrc`` and
KWin is asked to reload its settings.

Wallpaper and the cursor and Plasma themes record their previous value in
``undo_journal`` (kinds ``wallpaper`` and ``theme``). Everything that
changes is ``change``; the lists are ``read``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from .. import session_dbus, undo_journal
from ..desktop_context import run_command
from .power import run_checked
from .registry import RISK_CHANGE, RISK_READ, Tool, ToolFailure, object_schema

ICON_CHANGER_PATHS = ("/usr/lib/plasma-changeicons", "/usr/libexec/plasma-changeicons")
# The first desktop's wallpaper as JSON. A slideshow's SlidePaths is one comma-separated string;
# an empty SlideInterval means Plasma's default.
_WALLPAPER_SCRIPT = ('var d = desktops()[0]; var p = d.wallpaperPlugin; d.currentConfigGroup = ["Wallpaper", p, "General"]; '
                     'print(JSON.stringify({plugin: p, image: String(d.readConfig("Image") || ""), '
                     'folders: String(d.readConfig("SlidePaths") || ""), interval: String(d.readConfig("SlideInterval") || "")}));')
SLIDESHOW_PLUGIN = "org.kde.slideshow"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".svg", ".avif", ".jxl", ".heic", ".tif", ".tiff")
_THEME_COMMANDS = {"cursor": "plasma-apply-cursortheme", "plasma": "plasma-apply-desktoptheme"}


def _evaluate(script: str) -> str:
    """Run a Plasma shell script and return what it printed, or "" when the shell cannot be reached."""
    result = run_command(["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                          script], timeout=10) if shutil.which("qdbus6") else {"ok": False}
    return result["stdout"].strip() if result["ok"] else ""


def current_wallpaper() -> dict[str, Any]:
    """The first desktop's wallpaper: ``{"image": path}``, ``{"slideshow": [folders], "interval": seconds|None}``,
    or ``{}`` when it cannot be read or is another kind (a colour, a picture of the day)."""
    try:
        state = json.loads(_evaluate(_WALLPAPER_SCRIPT) or "{}")
    except ValueError:
        return {}
    if state.get("plugin") == SLIDESHOW_PLUGIN:
        folders = [folder for folder in str(state.get("folders", "")).split(",") if folder]
        interval = str(state.get("interval", ""))
        return {"slideshow": folders, "interval": int(interval) if interval.isdigit() else None} if folders else {}
    image = str(state.get("image", "")).removeprefix("file://")
    return {"image": image} if state.get("plugin") == "org.kde.image" and os.path.isfile(image) else {}


def _has_images(folder: str) -> bool:
    for _directory, _subdirectories, files in os.walk(folder):
        if any(name.lower().endswith(IMAGE_EXTENSIONS) for name in files):
            return True
    return False


def apply_slideshow(folders: list[str], interval: int | None) -> None:
    """Show a slideshow of ``folders`` (absolute paths) on every desktop, changing picture every ``interval``
    seconds (Plasma's default when None). Raises ToolFailure unless every desktop then shows the slideshow."""
    script = ("var folders = %s; var interval = %s; var shown = [];\n"
              "desktops().forEach(function (d) {\n"
              "  d.wallpaperPlugin = %s;\n"
              "  d.currentConfigGroup = ['Wallpaper', %s, 'General'];\n"
              "  d.writeConfig('SlidePaths', folders);\n"
              "  if (interval) d.writeConfig('SlideInterval', interval);\n"
              "  d.reloadConfig();\n"
              "  shown.push(d.wallpaperPlugin);\n"
              "});\n"
              "print(shown.join(','));") % (json.dumps(",".join(folders)), json.dumps(interval),
                                            json.dumps(SLIDESHOW_PLUGIN), json.dumps(SLIDESHOW_PLUGIN))
    shown = _evaluate(script)
    if not shown or any(plugin != SLIDESHOW_PLUGIN for plugin in shown.split(",")):
        raise ToolFailure("the desktop did not switch to the slideshow"
                          + (f" (it shows {shown})" if shown else " (the Plasma shell did not answer)"))


def set_wallpaper(arguments: dict[str, Any]) -> str:
    image = str(arguments.get("image") or "").strip()
    folder = str(arguments.get("folder") or "").strip()
    if bool(image) == bool(folder):
        raise ToolFailure("give either 'image' (one picture) or 'folder' (a slideshow of its pictures)")
    previous = current_wallpaper()
    if folder:
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            raise ToolFailure(f"{folder} is not a folder that exists")
        if not _has_images(folder):
            raise ToolFailure(f"{folder} has no pictures in it")
        minutes = arguments.get("interval_minutes")
        if minutes is not None and (not isinstance(minutes, (int, float)) or not 0 < minutes <= 7 * 24 * 60):
            raise ToolFailure("'interval_minutes' must be a number of minutes, at most a week")
        apply_slideshow([folder], round(minutes * 60) if minutes is not None else None)
        done = f"Wallpaper is now a slideshow of the pictures in {folder}" + (
            f", changing every {minutes:g} minutes." if minutes is not None else ".")
    else:
        image = os.path.abspath(os.path.expanduser(image))
        if not os.path.isfile(image):
            raise ToolFailure(f"{image} is not an image file that exists")
        run_checked(["plasma-apply-wallpaperimage", image])
        if current_wallpaper().get("image") not in (image, None):
            raise ToolFailure(f"the desktop still does not show {image}")
        done = f"Wallpaper set to {image}."
    if previous:
        undo_journal.record("wallpaper", "Changed the wallpaper", previous)
    return done


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


INPUT = ("org.kde.KWin", "/org/kde/KWin/InputDevice", "org.kde.KWin.InputDeviceManager")
_INPUT_FIELDS = {"tap_to_click": ("tapToClick", "b"), "natural_scroll": ("naturalScroll", "b"),
                 "pointer_speed": ("pointerAcceleration", "d")}


def _input_devices() -> list[dict[str, Any]]:
    names = session_dbus.properties(*INPUT).get("devicesSysNames") or []
    devices = []
    for sysname in names:
        try:
            state = session_dbus.properties("org.kde.KWin", f"/org/kde/KWin/InputDevice/{sysname}", "org.kde.KWin.InputDevice")
        except session_dbus.DBusError:
            continue
        if state.get("pointer") or state.get("touchpad"):
            devices.append({"sysname": sysname, **state})
    return devices


def _dbus_devices() -> list[dict[str, Any]]:
    try:
        return _input_devices()
    except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
        raise ToolFailure(f"input devices are not available ({error})") from error


def input_devices(arguments: dict[str, Any]) -> str:
    lines = []
    for device in _dbus_devices():
        kind = "touchpad" if device.get("touchpad") else "mouse"
        extra = [f"speed {device.get('pointerAcceleration', 0):+.1f}"]
        if "naturalScroll" in device:
            extra.append(f"natural scrolling {'on' if device['naturalScroll'] else 'off'}")
        if device.get("touchpad") and "tapToClick" in device:
            extra.append(f"tap to click {'on' if device['tapToClick'] else 'off'}")
        lines.append(f"{device.get('name', device['sysname'])} ({kind}): {', '.join(extra)}")
    return "\n".join(lines) or "No mouse or touchpad was found."


def set_input_device(arguments: dict[str, Any]) -> str:
    wanted = str(arguments.get("device") or "").strip().lower()
    devices = _dbus_devices()
    if wanted in ("touchpad", "mouse"):
        chosen = [device for device in devices if bool(device.get("touchpad")) == (wanted == "touchpad")]
    else:
        chosen = [device for device in devices if wanted and wanted in str(device.get("name", "")).lower()]
    if not chosen:
        raise ToolFailure(f"no matching device. {input_devices({})}")
    changes = {key: arguments[key] for key in _INPUT_FIELDS if arguments.get(key) is not None}
    if not changes:
        raise ToolFailure("give at least one of tap_to_click, natural_scroll, pointer_speed")
    speed = changes.get("pointer_speed")
    if speed is not None and (isinstance(speed, bool) or not isinstance(speed, (int, float)) or not -1 <= speed <= 1):
        raise ToolFailure("'pointer_speed' must be a number from -1 (slowest) to 1 (fastest)")
    for key in ("tap_to_click", "natural_scroll"):
        if key in changes and not isinstance(changes[key], bool):
            raise ToolFailure(f"'{key}' must be true or false")
    for device in chosen:
        for key, value in changes.items():
            prop, signature = _INPUT_FIELDS[key]
            if prop in device:
                session_dbus.set_property("org.kde.KWin", f"/org/kde/KWin/InputDevice/{device['sysname']}",
                                          "org.kde.KWin.InputDevice", prop, signature,
                                          float(value) if signature == "d" else value)
    return "Changed " + ", ".join(device.get("name", device["sysname"]) for device in chosen) + "."


def set_key_repeat(arguments: dict[str, Any]) -> str:
    delay, rate = arguments.get("delay_ms"), arguments.get("rate")
    if delay is None and rate is None:
        raise ToolFailure("give 'delay_ms' (100 to 2000), 'rate' (keys per second, 1 to 100), or both")
    for name, value, low, high in (("delay_ms", delay, 100, 2000), ("rate", rate, 1, 100)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high):
            raise ToolFailure(f"'{name}' must be a number from {low} to {high}")
    for key, value in (("RepeatDelay", delay), ("RepeatRate", rate)):
        if value is not None:
            run_checked(["kwriteconfig6", "--file", "kcminputrc", "--group", "Keyboard", "--key", key, str(round(value))])
    run_checked(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])
    return "Key repeat updated" + (f": delay {round(delay)} ms" if delay is not None else "") + \
        (f", {round(rate)} per second" if rate is not None else "") + "."


def appearance_tools() -> list[Tool]:
    return [
        Tool("set_wallpaper", "Set the desktop wallpaper: one picture ('image'), or a slideshow of every picture "
             "in a folder ('folder'). It applies at once on every screen and checks that it took; no restart is "
             "needed.",
             object_schema({"image": {"type": "string", "description": "A picture file"},
                            "folder": {"type": "string", "description": "A folder of pictures, for a slideshow"},
                            "interval_minutes": {"type": "number",
                                                 "description": "Slideshow only: minutes per picture"}}),
             RISK_CHANGE, set_wallpaper,
             summarize=lambda a: f"Show a slideshow of {a['folder']} as the wallpaper" if a.get("folder")
             else f"Set the wallpaper to {a.get('image', '?')}"),
        Tool("set_accent_color", "Set the accent colour used for highlights.",
             object_schema({"color": {"type": "string", "description": "#rrggbb or a colour name"}}, ["color"]),
             RISK_CHANGE, set_accent_color, summarize=lambda a: f"Set the accent colour to {a.get('color', '?')}"),
        Tool("list_themes", "The installed cursor and Plasma themes and which are in use.", object_schema(),
             RISK_READ, list_themes, summarize=lambda a: "List themes"),
        Tool("set_theme", "Switch the cursor theme, the Plasma (panel and widget) theme, or the icon theme.",
             object_schema({"kind": {"type": "string", "enum": ["cursor", "plasma", "icons"]},
                            "name": {"type": "string"}}, ["kind", "name"]), RISK_CHANGE, set_theme,
             summarize=lambda a: f"Switch the {a.get('kind', '?')} theme to {a.get('name', '?')}"),
        Tool("input_devices", "Mice and touchpads with their speed, natural scrolling and tap-to-click.",
             object_schema(), RISK_READ, input_devices, summarize=lambda a: "List mice and touchpads"),
        Tool("set_input_device", "Change a mouse's or touchpad's speed, natural scrolling or tap-to-click.",
             object_schema({"device": {"type": "string", "description": "touchpad, mouse, or part of its name"},
                            "pointer_speed": {"type": "number", "description": "-1 slowest to 1 fastest"},
                            "natural_scroll": {"type": "boolean"}, "tap_to_click": {"type": "boolean"}}, ["device"]),
             RISK_CHANGE, set_input_device, summarize=lambda a: f"Change the {a.get('device', '?')} settings"),
        Tool("set_key_repeat", "Set how soon a held key starts repeating and how fast it repeats.",
             object_schema({"delay_ms": {"type": "number"}, "rate": {"type": "number"}}), RISK_CHANGE, set_key_repeat,
             summarize=lambda a: "Change key repeat"),
        Tool("keyboard_layouts", "The configured keyboard layouts and which one is active.", object_schema(),
             RISK_READ, keyboard_layouts, summarize=lambda a: "List keyboard layouts"),
        Tool("set_keyboard_layout", "Switch to one of the configured keyboard layouts.",
             object_schema({"layout": {"type": "string", "description": "Its name or short code, e.g. de"}},
                           ["layout"]), RISK_CHANGE, set_keyboard_layout,
             summarize=lambda a: f"Switch the keyboard to {a.get('layout', '?')}"),
    ]
