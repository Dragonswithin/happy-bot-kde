"""Results the search bar shows while the user types, besides files: no model involved.

``gather(text, conversations, bookmarks, history)`` returns up to
``MAX_RESULTS`` results, best first (at most five applications, three
settings pages, eight characters, four bookmarks, four recently visited
websites and three conversations):

1. an instant command (``quick_commands``: "volume 30", "dark mode",
   "timer 10m", "lock"...), which runs at once through the built-in tools;
2. a computed answer (``quick_answers``: arithmetic, conversions, dates,
   world clocks), whose action copies it;
3. emoji and special characters (``characters``: "emoji heart", "euro
   sign"), which copy the character;
4. installed applications (``tools/apps.match_applications``), to start;
5. System Settings pages (the ``kcm_*.desktop`` entries Plasma ships, which
   the launcher hides), to open;
6. browser bookmarks and recently visited websites, each only when the user
   switched it on (``ui.search_bookmarks``, ``ui.search_history``), from the
   in-memory ``browsers.BrowserIndex``, to open in the default browser;
7. saved conversations whose title matches, to reopen.

``recent(conversations, websites)`` is what the empty bar suggests before
anything is typed: the applications, files and System Settings pages used
last (``usage_history``, KDE's own record of them), recent websites from that
record only when the user switched recent websites on, and the latest saved
chats. Files are file hits (``{title, location, snippet, kind}``, as the
file search returns) so their menu works as for any file.

Open windows are not offered: the maintainer found them odd among search
results (the task switcher is for those).

Each result is ``{"kind": "quick", "title", "subtitle", "icon", "action":
{"type", "target"}}``. The applet shows them above the file matches and sends
the action back to ``activate`` (``POST /quick/activate``), except
``conversation``, which it opens itself. Action types: ``copy`` and
``character`` (put ``target`` on the clipboard), ``command`` (run the
instant command typed as ``target``; needs the daemon, see ``activate``),
``phone`` (send the file ``target`` to the user's phone through KDE Connect,
``tools/phone.send_to_device``), ``launch``
(start the ``.desktop`` file at ``target``), ``settings`` (open System
Settings at the module ``target``), ``bookmark`` and ``visited`` (open the
web address ``target`` with ``xdg-open``), ``reveal`` (show the file ``target``
selected in the file manager, through ``org.freedesktop.FileManager1``; the
applet offers it, with ``copy``, on a file match's right-click menu).

Text shorter than ``MIN_CHARS`` yields only answers. Gathering reads
``.desktop`` files, which are cached for ``CACHE_SECONDS``; a failing source
is skipped, never fatal.
"""

from __future__ import annotations

import configparser
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import browsers, characters, quick_answers, quick_commands, usage_history
from .runtime_paths import read_clear_time, write_private_file
from .tools import apps
from .web_preferences import site_field

MAX_RESULTS = 20
_browsers = browsers.BrowserIndex()
MIN_CHARS = 2
CACHE_SECONDS = 60.0
WEB_QUERY_COUNT = 8
WEB_QUERY_LENGTH = 512
SETTINGS_DIRS = (Path("/usr/share/applications"), Path("/usr/local/share/applications"))
_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_cache_lock = threading.Lock()


class ActivationError(RuntimeError):
    """The chosen result could not be carried out; the message says why."""


class SearchHistory:
    """Remember when earlier suggestions were cleared, without editing source databases.

    Each clear replaces the browser index so an already-running refresh finishes
    into the retired index. Explicit web queries live in the session's private
    runtime directory, tagged with the same cutoff so older copies stay cleared.
    """

    def __init__(self, marker: Path, query_file: Path) -> None:
        self.marker = marker
        self.query_file = query_file
        self.index = browsers.BrowserIndex(history_since=read_clear_time(marker))
        self._lock = threading.Lock()
        self._queries: list[str] = []
        try:
            data = json.loads(query_file.read_text(encoding="utf-8"))
            if (isinstance(data, dict) and data.get("since") == self.index.history_since
                    and isinstance(data.get("queries"), list)):
                self._queries = [q for q in data["queries"] if isinstance(q, str)
                                 and 0 < len(q) <= WEB_QUERY_LENGTH][:WEB_QUERY_COUNT]
        except (OSError, ValueError):
            pass

        self.removed_file = marker.with_name("recent-dismissed.json")
        self._removed: dict[str, float] = {}
        try:
            removed = json.loads(self.removed_file.read_text(encoding="utf-8"))
            if isinstance(removed, dict):
                self._removed = {key: value for key, value in removed.items()
                                 if type(value) in (int, float) and math.isfinite(value)}
        except (OSError, ValueError):
            pass

    def removed_recent(self) -> dict[str, float]:
        with self._lock:
            return self._removed.copy()

    def remove_recent(self, kind: Any, target: Any) -> None:
        if (not isinstance(target, str) or len(target) > 8192 or "\0" in target or
                not ((kind == "file" and target.startswith("/")) or
                     (kind == "website" and site_field(target)))):
            raise ValueError("Choose a recent file or website.")
        with self._lock:
            removed = {**self._removed, target: time.time()}
            write_private_file(self.removed_file, json.dumps(removed))
            self._removed = removed

    def web_queries(self) -> list[str]:
        with self._lock:
            return list(self._queries)

    def remember_web_query(self, query: Any, revision: Any = None) -> None:
        """Remember the user's explicit search. Ignore a request sent before a clear."""
        if not isinstance(query, str) or not query.strip() or len(query) > WEB_QUERY_LENGTH:
            raise ValueError(f"Choose a search between 1 and {WEB_QUERY_LENGTH} characters.")
        if revision is not None and (type(revision) not in (int, float) or not 0 <= revision < math.inf):
            raise ValueError("Invalid search history revision.")
        query = " ".join(query.split())
        with self._lock:
            if revision is not None and revision < self.index.history_since:
                return
            queries = [query, *(q for q in self._queries if q.casefold() != query.casefold())][:WEB_QUERY_COUNT]
            if queries != self._queries:
                data = {"since": self.index.history_since, "queries": queries}
                write_private_file(self.query_file, json.dumps(data, ensure_ascii=False))
                self._queries = queries

    def clear(self) -> None:
        global _cache
        with self._lock:
            since = time.time()
            self.marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            write_private_file(self.marker, str(since))
            self.index = browsers.BrowserIndex(history_since=since)
            self._queries.clear()
            self.query_file.unlink(missing_ok=True)
            self.removed_file.unlink(missing_ok=True)
            self._removed.clear()
        with _cache_lock:
            _cache = {}


def _cached(key: str, load) -> list[dict[str, str]]:
    with _cache_lock:
        cache = _cache
        stamp, value = cache.get(key, (0.0, []))
        if time.monotonic() - stamp < CACHE_SECONDS and value:
            return value
    value = load()
    with _cache_lock:
        cache[key] = (time.monotonic(), value)
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


def _pages(text: str, bookmarks: bool, history: bool, index: browsers.BrowserIndex, removed: dict[str, float] | None) -> list[dict[str, Any]]:
    if not (bookmarks or history):
        return []
    index.refresh_in_background(history)
    marked, visited = index.search(text, bookmarks, history, removed=removed)
    return [{"kind": "quick", "title": page.title or browsers.host(page.url),
             "subtitle": f"{'Bookmark' if page.bookmark else 'Visited'} · {browsers.host(page.url)} · {page.browser}",
             "icon": page.icon, **site_field(page.url), "action": {"type": "bookmark" if page.bookmark else "visited", "target": page.url}}
            for page in [*marked, *visited]]


def gather(text: str, conversations: list[dict[str, Any]] | None = None,
           bookmarks: bool = False, history: bool = False, index: browsers.BrowserIndex | None = None, *,
           removed: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """Quick results for the typed text, best first (see module docstring)."""
    text = text.strip()
    results: list[dict[str, Any]] = quick_commands.match(text) if text else []
    answer = quick_answers.answer(text) if text else None
    if answer:
        results.append({"kind": "quick", "title": answer["title"], "subtitle": answer["subtitle"],
                        "icon": "accessories-calculator", "action": {"type": "copy", "target": answer["value"]}})
    if len(text) < MIN_CHARS or answer:
        return results
    try:
        results.extend(characters.find(text))
    except Exception:  # noqa: BLE001 - an unreadable emoji dictionary must not hide the rest
        pass
    for source, most in ((_applications, 5), (_settings, 3)):
        try:
            results.extend(source(text)[:most])
        except Exception:  # noqa: BLE001 - one broken source must not hide the others
            continue
    try:
        results.extend(_pages(text, bookmarks, history, index or _browsers, removed))
    except Exception:  # noqa: BLE001 - a browser database that cannot be read must not hide the rest
        pass
    results.extend(_conversations(text, conversations or [])[:3])
    return results[:MAX_RESULTS]


TRANSIENT_FOLDERS = ("/tmp/", "/run/", "/proc/", "/dev/")  # files there are gone or not the user's own
RECENT_LIMITS = {"applications": 6, "files": 6, "settings": 3, "websites": 4, "chats": 3}


def recent(conversations: list[dict[str, Any]] | None = None, websites: bool = False,
           database: Path | None = None, *, since: float = 0,
           removed: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """What the empty bar suggests: recently used applications, files, settings, websites and chats."""
    found: dict[str, list[dict[str, Any]]] = {kind: [] for kind in RECENT_LIMITS}
    try:
        applications = {app["id"]: app for app in _cached("apps", apps.installed_applications)}
        pages = {page["module"]: page for page in _cached("settings", settings_pages)}
    except Exception:  # noqa: BLE001 - without the lists, only files, websites and chats are suggested
        applications, pages = {}, {}
    from .app_control import DESKTOP_FILE
    transient = TRANSIENT_FOLDERS + ((os.environ["XDG_RUNTIME_DIR"].rstrip("/") + "/",)
                                     if os.environ.get("XDG_RUNTIME_DIR") else ())
    for item in usage_history.recent_resources(database):
        if since and item.last_used <= since:
            continue
        target = item.target
        if removed and item.last_used <= removed.get(target.removeprefix("file://"), 0):
            continue
        if target.startswith("applications:"):
            app = applications.get(target.removeprefix("applications:"))
            if app and app["id"] != DESKTOP_FILE:
                found["applications"].append({
                    "kind": "quick", "title": app["name"], "subtitle": "Application" + (f" · {app['generic']}" if app["generic"] else ""),
                    "icon": _desktop_icon(app["path"]), "action": {"type": "launch", "target": app["path"]}})
        elif target.startswith("kcm:"):
            page = pages.get(target.removeprefix("kcm:"))
            if page:
                found["settings"].append({"kind": "quick", "title": page["name"], "subtitle": "System Settings",
                                          "icon": page["icon"], "action": {"type": "settings", "target": page["module"]}})
        elif target.startswith(("http://", "https://")):
            if websites:
                found["websites"].append({"kind": "quick", "title": item.title or browsers.host(target),
                                          "subtitle": f"Visited · {browsers.host(target)}", "icon": "internet-web-browser",
                                          "action": {"type": "visited", "target": target}})
        else:
            path = target.removeprefix("file://")
            if path.startswith("/") and not path.startswith(transient) and os.path.exists(path):
                name = os.path.basename(path.rstrip("/")) or path
                found["files"].append({"title": name, "location": path, "snippet": "",
                                       "kind": "folder" if os.path.isdir(path) else "file"})
    found["chats"] = [{"kind": "quick", "title": item["title"], "subtitle": "Earlier conversation", "icon": "view-history",
                       "action": {"type": "conversation", "target": item["id"]}}
                      for item in sorted(conversations or [], key=lambda c: c.get("updated", 0), reverse=True)
                      if not since or item.get("updated", 0) > since]
    unique: dict[str, dict[str, Any]] = {}
    for kind, items in found.items():
        for item in items[:RECENT_LIMITS[kind]]:
            unique.setdefault(item.get("location") or f"{item['action']['type']}:{item['action']['target']}", item)
    return list(unique.values())


def _start(command: list[str]) -> None:
    if not shutil.which(command[0]):
        raise ActivationError(f"'{command[0]}' is not installed")
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as error:
        raise ActivationError(str(error)) from error


def activate(action: dict[str, Any], server: Any = None) -> str:
    """Carry out a result's action; returns a short description, or raises ``ActivationError``.

    ``command`` and ``phone`` need ``server`` (the daemon: its settings and
    runtime directory, for the tools and the action log); without it they are
    refused.
    """
    kind, target = action.get("type"), str(action.get("target") or "")
    if not target:
        raise ActivationError("the result has no target")
    if kind in ("command", "phone") and server is None:
        raise ActivationError("only Happy Bot's daemon can do that")
    if kind == "command":
        try:
            return quick_commands.run(target, server.settings.get("agent"), server.runtime_dir)
        except quick_commands.CommandError as error:
            raise ActivationError(str(error)) from error
    if kind == "phone":
        from .permissions import append_audit
        from .tools.phone import send_to_device
        from .tools.registry import ToolFailure
        try:
            report = send_to_device({"file_or_url": target})
        except ToolFailure as error:
            raise ActivationError(str(error)) from error
        append_audit(server.runtime_dir, {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool": "send_to_device",
                                          "risk": "change", "outcome": "ran from the search bar",
                                          "arguments": target[:2000]})
        return report
    if kind in ("copy", "character"):
        if shutil.which("wl-copy"):
            _start(["wl-copy", "--", target])
        else:
            _start(["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", target])
        return f"Copied {target}"
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
    if kind in ("bookmark", "visited"):
        if not re.match(r"https?://[^\s]+$", target):
            raise ActivationError("not a web address")
        _start(["xdg-open", target])
        return f"Opened {browsers.host(target)}"
    if kind == "settings":
        if not re.fullmatch(r"kcm_[A-Za-z0-9_.-]+", target):
            raise ActivationError("not a System Settings page")
        _start(["systemsettings", target])
        return f"Opened {target}"
    raise ActivationError(f"unknown action {kind!r}")
