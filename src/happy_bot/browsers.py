"""The user's web browsers: their profiles, bookmarks and recent history, read on this computer.

Two consumers: the search results (``quick_results``: "Bookmarks" and "Recent websites" while the
user types in the panel bar or "Find a file", each switched on separately in the Appearance
settings, ``ui.search_bookmarks`` / ``ui.search_history``), and the assistant's
``browser_bookmarks`` tool (``tools/finding.py``).

Profiles (``profiles``) are looked for where the major browsers keep them, natively and as
Flatpaks (``~/.var/app/<id>/...``):

- Firefox family (Firefox, LibreWolf, Floorp, Zen, Waterfox): each profile folder holding a
  ``places.sqlite`` (bookmarks and history in one database).
- Chromium family (Chromium, Chrome, Brave, Vivaldi, Edge, Opera): each profile folder
  ("Default", "Profile 1", ...; Opera's folder itself) holding ``Bookmarks`` (JSON) and/or
  ``History`` (SQLite).

Folders whose names look like copies (``backup``, ``back-``, ``crashrecovery``) are skipped.
Browsers keep their databases open and locked, so each is copied, with its write-ahead log when
there is one (where the newest history sits), into a private temporary folder and read there
read-only; the copy is deleted at once. Nothing is written to a browser's files.

``BrowserIndex`` keeps one list of everything in memory for the search: bookmarks, and of
history the ``HISTORY_PER_PROFILE`` most recently visited pages of each profile visited within
``HISTORY_DAYS``. It is rebuilt in the background (``refresh_in_background``) when older than
``REFRESH_SECONDS``, so a keystroke never waits for a database copy; the first search after
switching it on may show no browser results yet. ``search`` matches every typed word in a
page's title or address, bookmarks before history, history by visit count then recency, one
result per address. The history stays in memory only and never leaves the computer.
"""

from __future__ import annotations

import json
from contextlib import closing
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HISTORY_DAYS = 90
HISTORY_PER_PROFILE = 5000
REFRESH_SECONDS = 60.0
_COPY_NAME = re.compile(r"backup|back-|crashrecovery", re.IGNORECASE)
# Firefox family: (browser name, icon, folders under home or a Flatpak's home that hold profiles)
FIREFOX_FAMILY = (
    ("Firefox", "firefox", (".mozilla/firefox", ".var/app/org.mozilla.firefox/.mozilla/firefox")),
    ("LibreWolf", "librewolf", (".librewolf", ".var/app/io.gitlab.librewolf-community/.librewolf")),
    ("Floorp", "floorp", (".floorp", ".var/app/one.ablaze.floorp/.floorp")),
    ("Zen", "zen-browser", (".zen", ".var/app/app.zen_browser.zen/.zen")),
    ("Waterfox", "waterfox", (".waterfox", ".var/app/net.waterfox.waterfox/.waterfox")),
)
# Chromium family: (browser name, icon, folders under ~/.config or a Flatpak's config)
CHROMIUM_FAMILY = (
    ("Chromium", "chromium", ("chromium", "../.var/app/org.chromium.Chromium/config/chromium")),
    ("Chrome", "google-chrome", ("google-chrome", "../.var/app/com.google.Chrome/config/google-chrome")),
    ("Brave", "brave-browser", ("BraveSoftware/Brave-Browser",
                                "../.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser")),
    ("Vivaldi", "vivaldi", ("vivaldi", "../.var/app/com.vivaldi.Vivaldi/config/vivaldi")),
    ("Edge", "microsoft-edge", ("microsoft-edge", "../.var/app/com.microsoft.Edge/config/microsoft-edge")),
    ("Opera", "opera", ("opera", "../.var/app/com.opera.Opera/config/opera")),
)


@dataclass(frozen=True)
class Profile:
    browser: str          # "Firefox", "Brave", ...
    icon: str             # the browser's theme icon name
    family: str           # "firefox" or "chromium"
    folder: Path


@dataclass(frozen=True)
class Page:
    title: str
    url: str
    browser: str
    icon: str
    bookmark: bool
    visits: int = 0
    visited: float = 0.0  # seconds since the epoch; 0 for a bookmark


def profiles(home: Path | None = None, config: Path | None = None) -> list[Profile]:
    """Every browser profile found on this computer (see the module docstring)."""
    home = home or Path.home()
    config = config or Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    found: list[Profile] = []
    for browser, icon, places in FIREFOX_FAMILY:
        for place in places:
            for database in sorted((home / place).glob("*/places.sqlite")):
                if not _COPY_NAME.search(database.parent.name):
                    found.append(Profile(browser, icon, "firefox", database.parent))
    for browser, icon, places in CHROMIUM_FAMILY:
        for place in places:
            root = (config / place).resolve()
            candidates = [root, *sorted(root.glob("*"))] if root.is_dir() else []
            for folder in candidates:
                if folder.is_dir() and not _COPY_NAME.search(folder.name) \
                        and ((folder / "Bookmarks").is_file() or (folder / "History").is_file()):
                    found.append(Profile(browser, icon, "chromium", folder))
    return list(dict.fromkeys(found))


def _with_copy(database: Path, query: str, parameters: tuple = ()) -> list[tuple]:
    """Rows of ``query`` from a private copy of a browser's (locked, live) SQLite database."""
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / database.name
        try:
            shutil.copyfile(database, copy)
            for suffix in ("-wal", "-journal"):
                if database.with_name(database.name + suffix).is_file():
                    shutil.copyfile(database.with_name(database.name + suffix), copy.with_name(copy.name + suffix))
            # closing(): "with connection" alone only ends a transaction and leaves the file open.
            with closing(sqlite3.connect(f"file:{copy}?mode=ro", uri=True)) as connection:
                return connection.execute(query, parameters).fetchall()
        except (OSError, sqlite3.Error):
            return []


def chromium_bookmarks(path: Path) -> list[tuple[str, str]]:
    """``(title, url)`` of every bookmark in a Chromium-family ``Bookmarks`` file."""
    found: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "url":
                found.append((str(node.get("name") or ""), str(node.get("url") or "")))
            for child in node.get("children", []) or []:
                walk(child)
            for child in (node.get("roots") or {}).values():
                walk(child)

    try:
        walk(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return found


def firefox_bookmarks(path: Path) -> list[tuple[str, str]]:
    """``(title, url)`` of every bookmark in a Firefox-family ``places.sqlite``."""
    rows = _with_copy(path, "SELECT b.title, p.url FROM moz_bookmarks b JOIN moz_places p ON b.fk = p.id WHERE b.type = 1")
    return [(title or "", url) for title, url in rows]


def _history(profile: Profile, since: float) -> list[Page]:
    if profile.family == "firefox":  # last_visit_date: microseconds since 1970
        rows = _with_copy(profile.folder / "places.sqlite",
                          "SELECT url, title, visit_count, last_visit_date / 1000000.0 FROM moz_places "
                          "WHERE hidden = 0 AND last_visit_date >= ? ORDER BY last_visit_date DESC LIMIT ?",
                          (int(since * 1_000_000), HISTORY_PER_PROFILE))
    else:  # last_visit_time: microseconds since 1601-01-01
        offset = 11_644_473_600
        rows = _with_copy(profile.folder / "History",
                          "SELECT url, title, visit_count, last_visit_time / 1000000.0 - ? FROM urls "
                          "WHERE hidden = 0 AND last_visit_time >= ? ORDER BY last_visit_time DESC LIMIT ?",
                          (offset, int((since + offset) * 1_000_000), HISTORY_PER_PROFILE))
    return [Page(title or "", url, profile.browser, profile.icon, False, int(visits or 0), float(visited or 0))
            for url, title, visits, visited in rows if str(url).startswith(("http://", "https://"))]


def _bookmarks(profile: Profile) -> list[Page]:
    pairs = firefox_bookmarks(profile.folder / "places.sqlite") if profile.family == "firefox" \
        else chromium_bookmarks(profile.folder / "Bookmarks")
    return [Page(title, url, profile.browser, profile.icon, True) for title, url in pairs
            if url.startswith(("http://", "https://"))]


def _key(url: str) -> str:
    return url.rstrip("/").lower()


class BrowserIndex:
    """Bookmarks and recent history of every profile, in memory, refreshed in the background."""

    def __init__(self, home: Path | None = None, config: Path | None = None) -> None:
        self._home, self._config = home, config
        self._lock = threading.Lock()
        self._pages: list[Page] = []
        self._built = 0.0
        self._building = False
        self._history_wanted = False

    def build(self, history: bool) -> None:
        """Read everything now (blocking: copies the browsers' databases)."""
        since = time.time() - HISTORY_DAYS * 86400
        pages: list[Page] = []
        for profile in profiles(self._home, self._config):
            pages += _bookmarks(profile)
            if history:
                pages += _history(profile, since)
        with self._lock:
            self._pages, self._built, self._history_wanted = pages, time.monotonic(), history

    def refresh_in_background(self, history: bool) -> None:
        """Rebuild on a thread when stale (or when history was just switched on); never blocks."""
        with self._lock:
            fresh = time.monotonic() - self._built < REFRESH_SECONDS and self._built and history <= self._history_wanted
            if fresh or self._building:
                return
            self._building = True

        def run() -> None:
            try:
                self.build(history)
            finally:
                with self._lock:
                    self._building = False

        threading.Thread(target=run, name="browser-index", daemon=True).start()

    def search(self, text: str, bookmarks: bool, history: bool, most: int = 4) -> tuple[list[Page], list[Page]]:
        """``(bookmarks, history)`` matching every word of ``text``, at most ``most`` of each."""
        words = text.lower().split()
        if not words or not (bookmarks or history):
            return [], []
        with self._lock:
            pages = list(self._pages)
        matches = [page for page in pages if all(word in f"{page.title} {page.url}".lower() for word in words)]
        seen: set[str] = set()
        marked: list[Page] = []
        for page in matches:
            if page.bookmark and _key(page.url) not in seen:
                seen.add(_key(page.url))
                marked.append(page)
        visited: list[Page] = []
        for page in sorted((page for page in matches if not page.bookmark), key=lambda p: (-p.visits, -p.visited)):
            if _key(page.url) not in seen:
                seen.add(_key(page.url))
                visited.append(page)
        return (marked[:most] if bookmarks else []), (visited[:most] if history else [])


def host(url: str) -> str:
    return urlsplit(url).hostname or url
