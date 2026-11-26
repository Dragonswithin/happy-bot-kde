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
- Ladybird: named profiles under the XDG config and data directories, with
  ``Bookmarks.json`` in config and ``History.db`` in data.

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

import base64
import json
from collections import Counter
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

from .web_preferences import site_identity

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
    bookmark_folder: Path | None = None


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
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    flatpak = home / ".var/app/org.ladybird.Ladybird"
    for config_home, data_home in ((config, data), (flatpak / "config", flatpak / "data")):
        config_profiles = config_home / "Ladybird/Profiles"
        data_profiles = data_home / "Ladybird/Profiles"
        names = {p.parent.name for p in config_profiles.glob("*/Bookmarks.json")}
        names.update(p.parent.name for p in data_profiles.glob("*/History.db"))
        for name in sorted(names):
            if not _COPY_NAME.search(name):
                found.append(Profile("Ladybird", "org.ladybird.Ladybird", "ladybird",
                                     data_profiles / name, config_profiles / name))
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


def _favicon_data_url(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\x00\x00\x01\x00"):
        mime = "image/x-icon"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        return ""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _icon_origins(homepage: str) -> tuple[str, ...]:
    parts = urlsplit(homepage)
    alternate_scheme = "http" if parts.scheme == "https" else "https"
    if parts.port is not None:
        return (homepage,)
    origins = [homepage, f"{alternate_scheme}://{parts.netloc}/"]
    alias = parts.netloc.removeprefix("www.") if parts.netloc.startswith("www.") else f"www.{parts.netloc}"
    identity = site_identity(homepage)
    for scheme in (parts.scheme, alternate_scheme):
        origin = f"{scheme}://{alias}/"
        variant = site_identity(origin)
        if identity and variant and variant[0] == identity[0]:
            origins.append(origin)
    return tuple(origins)


def _profile_favicons(profile: Profile, sites: dict[str, str]) -> dict[str, str]:
    names = {"firefox": "favicons.sqlite", "chromium": "Favicons", "ladybird": "History.db"}
    path = profile.folder / names[profile.family]
    if not path.is_file():
        return {}
    # Prefer an icon assigned to the homepage, then one used by another
    # page on that origin. Firefox can also store a separate root icon.
    if profile.family == "firefox":
        candidates = """
            SELECT p.page_url AS url, i.width, i.data AS image
            FROM moz_pages_w_icons p JOIN moz_icons_to_pages link ON link.page_id = p.id
            JOIN moz_icons i ON i.id = link.icon_id
            WHERE p.page_url >= :origin AND p.page_url < :end
            UNION ALL
            SELECT :origin, width, data FROM moz_icons
            WHERE root = 1 AND icon_url >= :origin AND icon_url < :end
        """
    elif profile.family == "ladybird":
        candidates = """
            SELECT h.url, 48 AS width, f.png_data AS image
            FROM History h JOIN Favicons f ON f.hash = h.favicon_hash
            WHERE h.url >= :origin AND h.url < :end
        """
    else:
        candidates = """
            SELECT m.page_url AS url, b.width, b.image_data AS image
            FROM icon_mapping m JOIN favicon_bitmaps b ON b.icon_id = m.icon_id
            WHERE m.page_url >= :origin AND m.page_url < :end
        """
    query = f"""SELECT image FROM ({candidates}) WHERE length(image) BETWEEN 1 AND 65536
                ORDER BY url != :origin, abs(width - 48) LIMIT 8"""
    found = {}
    try:
        # A read-only connection can see the browser's current WAL. If the
        # profile is locked or unavailable, the site still has its monogram.
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)) as db:
            for host, homepage in sites.items():
                for origin in _icon_origins(homepage):
                    rows = db.execute(query, {"origin": origin, "end": origin[:-1] + "0"})
                    icons = (_favicon_data_url(data) for (data,) in rows if isinstance(data, bytes))
                    if icon := next(filter(None, icons), ""):
                        found[host] = icon
                        break
    except (OSError, sqlite3.Error):
        pass
    return found


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


def _history(profile: Profile, since: float, after_clear: bool) -> list[Page]:
    if profile.family == "firefox":  # last_visit_date: microseconds since 1970
        cutoff = int(since * 1_000_000)
        count = "(SELECT COUNT(*) FROM moz_historyvisits WHERE place_id = p.id AND visit_date >= ?)" if after_clear else "visit_count"
        rows = _with_copy(profile.folder / "places.sqlite",
                          f"SELECT url, title, {count}, last_visit_date / 1000000.0 FROM moz_places p "
                          "WHERE hidden = 0 AND last_visit_date >= ? ORDER BY last_visit_date DESC LIMIT ?",
                          ((cutoff,) if after_clear else ()) + (cutoff, HISTORY_PER_PROFILE))
    elif profile.family == "ladybird":  # last_visited_time: Unix seconds
        # Ladybird stores a lifetime count per URL, with no individual visit rows.
        count = "1" if after_clear else "visit_count"
        rows = _with_copy(profile.folder / "History.db",
                          f"SELECT url, title, {count}, last_visited_time FROM History "
                          "WHERE last_visited_time >= ? ORDER BY last_visited_time DESC LIMIT ?",
                          (since, HISTORY_PER_PROFILE))
    else:  # last_visit_time: microseconds since 1601-01-01
        offset = 11_644_473_600
        cutoff = int((since + offset) * 1_000_000)
        count = "(SELECT COUNT(*) FROM visits WHERE visits.url = p.id AND visit_time >= ?)" if after_clear else "visit_count"
        rows = _with_copy(profile.folder / "History",
                          f"SELECT url, title, {count}, last_visit_time / 1000000.0 - ? FROM urls p "
                          "WHERE hidden = 0 AND last_visit_time >= ? ORDER BY last_visit_time DESC LIMIT ?",
                          ((cutoff,) if after_clear else ()) + (offset, cutoff, HISTORY_PER_PROFILE))
    return [Page(title or "", url, profile.browser, profile.icon, False, int(visits or 0), float(visited or 0))
            for url, title, visits, visited in rows if str(url).startswith(("http://", "https://"))]


def _ladybird_bookmarks(path: Path) -> list[tuple[str, str]]:
    def walk(items: Any):
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "folder":
                yield from walk(item.get("children"))
            elif item.get("type") == "bookmark" and isinstance(item.get("url"), str):
                yield str(item.get("title") or ""), item["url"]

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return list(walk(document.get("items"))) if isinstance(document, dict) else []
    except (OSError, ValueError, RecursionError):
        return []


def _bookmarks(profile: Profile) -> list[Page]:
    if profile.family == "ladybird":
        pairs = _ladybird_bookmarks((profile.bookmark_folder or profile.folder) / "Bookmarks.json")
    elif profile.family == "firefox":
        pairs = firefox_bookmarks(profile.folder / "places.sqlite")
    else:
        pairs = chromium_bookmarks(profile.folder / "Bookmarks")
    return [Page(title, url, profile.browser, profile.icon, True) for title, url in pairs
            if url.startswith(("http://", "https://"))]


def _key(url: str) -> str:
    return url.rstrip("/").lower()


class BrowserIndex:
    """Bookmarks and recent history of every profile, in memory, refreshed in the background."""

    def __init__(self, home: Path | None = None, config: Path | None = None, *, history_since: float = 0) -> None:
        self._home, self._config = home, config
        self.history_since = history_since
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._pages: list[Page] = []
        self._built = 0.0
        self._building = False
        self._history_wanted = False

    def build(self, history: bool) -> None:
        """Read everything now (blocking: copies the browsers' databases)."""
        since = max(self.history_since, time.time() - HISTORY_DAYS * 86400)
        pages: list[Page] = []
        for profile in profiles(self._home, self._config):
            pages += _bookmarks(profile)
            if history:
                pages += _history(profile, since, after_clear=self.history_since > 0)
        with self._lock:
            self._pages, self._built, self._history_wanted = pages, time.monotonic(), history

    def _fresh(self, history: bool) -> bool:
        return self._built > 0 and time.monotonic() - self._built < REFRESH_SECONDS and (not history or self._history_wanted)

    def _refresh(self, history: bool) -> None:
        # A web start page and a typed search can ask for the same cold index at once.
        with self._refresh_lock:
            with self._lock:
                if self._fresh(history):
                    return
            self.build(history)

    def refresh_in_background(self, history: bool) -> None:
        """Rebuild on a thread when stale (or when history was just switched on); never blocks."""
        with self._lock:
            if self._fresh(history) or self._building:
                return
            self._building = True

        def run() -> None:
            try:
                self._refresh(history)
            finally:
                with self._lock:
                    self._building = False

        threading.Thread(target=run, name="browser-index", daemon=True).start()

    def frequent_sites(self) -> list[dict[str, str]]:
        """Homepage shortcuts by total visits across profiles, with recent ties first."""
        self._refresh(history=True)
        with self._lock:
            pages = self._pages  # build replaces the list, never mutates it
        counts: Counter[str] = Counter()
        latest: dict[str, tuple[float, str]] = {}
        titles: dict[str, tuple[float, str]] = {}
        for page in pages:
            if page.bookmark or page.visits <= 0:
                continue
            identity = site_identity(page.url)
            if identity is None:
                continue
            host, location = identity
            counts[host] += page.visits
            latest[host] = max(latest.get(host, (0.0, "")), (page.visited, location))
            parts = urlsplit(page.url)
            if parts.path in ("", "/") and not parts.query and not parts.fragment and page.title.strip():
                titles[host] = max(titles.get(host, (0.0, "")), (page.visited, page.title.strip()[:160]))
        ranked = sorted(counts, key=lambda host: (-counts[host], -latest[host][0], host))
        return [{"host": host, "title": titles.get(host, (0, host))[1], "location": latest[host][1]} for host in ranked]

    def favicons(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        """Read icons for these displayed sites from local browser caches only."""
        pending = {row["host"]: row["location"] for row in rows}
        if not pending:
            return {}
        icons = {}
        for profile in profiles(self._home, self._config):
            icons.update(_profile_favicons(profile, pending))
            pending = {host: url for host, url in pending.items() if host not in icons}
            if not pending:
                break
        return icons

    def search(self, text: str, bookmarks: bool, history: bool, most: int = 4, *,
               removed: dict[str, float] | None = None) -> tuple[list[Page], list[Page]]:
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
            if _key(page.url) not in seen and (not removed or page.visited > removed.get(page.url, 0)):
                seen.add(_key(page.url))
                visited.append(page)
        return (marked[:most] if bookmarks else []), (visited[:most] if history else [])


def host(url: str) -> str:
    return urlsplit(url).hostname or url
