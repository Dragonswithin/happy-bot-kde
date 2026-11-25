"""Results the search bar shows while the user types, besides files: no model involved.

``gather(text, conversations)`` returns up to ``MAX_RESULTS`` results, best
first (at most three windows, five applications, three settings pages and
three conversations):

1. a computed answer (``quick_answers``: arithmetic, conversions, dates,
   world clocks), whose action copies it;
2. open windows whose title or application matches, to switch to;
3. installed applications (``tools/apps.match_applications``), to start;
4. System Settings pages (the ``kcm_*.desktop`` entries Plasma ships, which
   the launcher hides), to open;
5. saved conversations whose title matches, to reopen.

Each result is ``{"kind": "quick", "title", "subtitle", "icon", "action":
{"type", "target"}}``. The applet shows them above the file matches and sends
the action back to ``activate`` (``POST /quick/activate``), except
``conversation``, which it opens itself. Action types: ``copy`` (put
``target`` on the clipboard), ``window`` (focus the window id), ``launch``
(start the ``.desktop`` file at ``target``), ``settings`` (open System
Settings at the module ``target``), ``reveal`` (show the file ``target``
selected in the file manager, through ``org.freedesktop.FileManager1``; the
applet offers it, with ``copy``, on a file match's right-click menu).

Text shorter than ``MIN_CHARS`` yields only answers. Gathering lists
windows through KWin (milliseconds) and reads ``.desktop`` files, which are
cached for ``CACHE_SECONDS``; a failing source is skipped, never fatal.
"""

from __future__ import annotations

import configparser
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import kwin_bridge, quick_answers
from .tools import apps

MAX_RESULTS = 12
MIN_CHARS = 2
CACHE_SECONDS = 60.0
SETTINGS_DIRS = (Path("/usr/share/applications"), Path("/usr/local/share/applications"))
_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_cache_lock = threading.Lock()


class ActivationError(RuntimeError):
    """The chosen result could not be carried out; the message says why."""


def _cached(key: str, load) -> list[dict[str, str]]:
    with _cache_lock:
        stamp, value = _cache.get(key, (0.0, []))
        if time.monotonic() - stamp < CACHE_SECONDS and value:
            return value
    value = load()
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
    return value


def settings_pages(directories: tuple[Path, ...] = SETTINGS_DIRS) -> list[dict[str, str]]:
    """System Settings modules: ``{module, name, comment, keywords, icon}``."""
    pages: dict[str, dict[str, str]] = {}
    for directory in directories:
        for path in sorted(directory.glob("kcm_*.desktop")) if directory.is_dir() else []:
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
                continue
            module = path.stem
            pages.setdefault(module, {"module": module, "name": entry.get("Name", module),
                                      "comment": entry.get("Comment", ""), "keywords": entry.get("Keywords", ""),
                                      "icon": entry.get("Icon", "preferences-system")})
    return list(pages.values())


def _words_match(text: str, haystack: str) -> bool:
    return all(word in haystack.lower() for word in text.lower().split())


def _windows(text: str) -> list[dict[str, Any]]:
    try:
        windows = kwin_bridge.shared().run(kwin_bridge.LIST_WINDOWS_JS)
    except (kwin_bridge.KWinUnavailable, kwin_bridge.KWinScriptError):
        return []
    return [{"kind": "quick", "title": window["title"] or window["app"], "subtitle": f"Window · {window['app']}",
             "icon": window["app"].lower() or "window", "action": {"type": "window", "target": window["id"]}}
            for window in windows if _words_match(text, f"{window['title']} {window['app']}")]


def _applications(text: str) -> list[dict[str, Any]]:
    found = apps.match_applications(text, _cached("apps", apps.installed_applications))
    return [{"kind": "quick", "title": app["name"], "subtitle": "Application" + (f" · {app['generic']}" if app["generic"] else ""),
             "icon": _desktop_icon(app["path"]), "action": {"type": "launch", "target": app["path"]}} for app in found]


def _desktop_icon(path: str) -> str:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
        return parser["Desktop Entry"].get("Icon", "application-x-executable")
    except (configparser.Error, KeyError, UnicodeDecodeError, OSError):
        return "application-x-executable"


def _settings(text: str) -> list[dict[str, Any]]:
    return [{"kind": "quick", "title": page["name"], "subtitle": "System Settings" + (f" · {page['comment']}" if page["comment"] else ""),
             "icon": page["icon"], "action": {"type": "settings", "target": page["module"]}}
            for page in _cached("settings", settings_pages)
            if _words_match(text, f"{page['name']} {page['keywords']} {page['comment']}")]


def _conversations(text: str, conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"kind": "quick", "title": item["title"], "subtitle": "Earlier conversation", "icon": "view-history",
             "action": {"type": "conversation", "target": item["id"]}}
            for item in conversations if _words_match(text, item.get("title", ""))]


def gather(text: str, conversations: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Quick results for the typed text, best first (see module docstring)."""
    text = text.strip()
    results: list[dict[str, Any]] = []
    answer = quick_answers.answer(text) if text else None
    if answer:
        results.append({"kind": "quick", "title": answer["title"], "subtitle": answer["subtitle"],
                        "icon": "accessories-calculator", "action": {"type": "copy", "target": answer["value"]}})
    if len(text) < MIN_CHARS or answer:
        return results
    for source, most in ((_windows, 3), (_applications, 5), (_settings, 3)):
        try:
            results.extend(source(text)[:most])
        except Exception:  # noqa: BLE001 - one broken source must not hide the others
            continue
    results.extend(_conversations(text, conversations or [])[:3])
    return results[:MAX_RESULTS]


def _start(command: list[str]) -> None:
    if not shutil.which(command[0]):
        raise ActivationError(f"'{command[0]}' is not installed")
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as error:
        raise ActivationError(str(error)) from error


def activate(action: dict[str, Any]) -> str:
    """Carry out a result's action; returns a short description, or raises ``ActivationError``."""
    kind, target = action.get("type"), str(action.get("target") or "")
    if not target:
        raise ActivationError("the result has no target")
    if kind == "copy":
        if shutil.which("wl-copy"):
            _start(["wl-copy", "--", target])
        else:
            _start(["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", target])
        return f"Copied {target}"
    if kind == "window":
        from .tools.windows import focus_window
        from .tools.registry import ToolFailure
        try:
            return focus_window({"window": target})
        except ToolFailure as error:
            raise ActivationError(str(error)) from error
    if kind == "launch":
        if not target.endswith(".desktop") or not Path(target).is_file():
            raise ActivationError("that application is no longer installed")
        _start(["gio", "launch", target])
        return f"Started {Path(target).stem}"
    if kind == "reveal":
        if not Path(target).exists():
            raise ActivationError(f"{target} no longer exists")
        from . import session_dbus
        try:
            session_dbus.call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                              "org.freedesktop.FileManager1", "ShowItems", "ass", ([Path(target).as_uri()], ""))
        except (session_dbus.DBusUnavailable, session_dbus.DBusError) as error:
            raise ActivationError(f"the file manager could not show it ({error})") from error
        return f"Showed {target} in the file manager"
    if kind == "settings":
        if not re.fullmatch(r"kcm_[A-Za-z0-9_.-]+", target):
            raise ActivationError("not a System Settings page")
        _start(["systemsettings", target])
        return f"Opened {target}"
    raise ActivationError(f"unknown action {kind!r}")
