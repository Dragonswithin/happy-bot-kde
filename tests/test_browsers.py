"""Tests for reading browser bookmarks and history (``browsers``) and showing them in search (``quick_results``).

A temporary home holds a Firefox profile (``places.sqlite`` with bookmarks and history), a
Flatpak Firefox profile, a Chromium profile (``Bookmarks`` JSON and a ``History`` database with
Chromium's 1601-based microsecond times) and a backup copy that must be skipped. Nothing of the
real user's browsers is read; opening a page is recorded instead of run.
"""

from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import browsers, quick_results  # noqa: E402

NOW = time.time()
DAY = 86400


def firefox_profile(folder: Path, bookmarks: list[tuple[str, str]], visits: list[tuple[str, str, int, float]]) -> None:
    folder.mkdir(parents=True)
    with closing(sqlite3.connect(folder / "places.sqlite")) as database, database:
        database.executescript("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, "
                               "hidden INTEGER DEFAULT 0, last_visit_date INTEGER);"
                               "CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER, title TEXT);")
        for title, url in bookmarks:
            place = database.execute("INSERT INTO moz_places (url, title, visit_count) VALUES (?, ?, 0)", (url, title)).lastrowid
            database.execute("INSERT INTO moz_bookmarks (type, fk, title) VALUES (1, ?, ?)", (place, title))
        for url, title, count, when in visits:
            database.execute("INSERT INTO moz_places (url, title, visit_count, last_visit_date) VALUES (?, ?, ?, ?)",
                             (url, title, count, int(when * 1_000_000)))


def chromium_profile(folder: Path, bookmarks: list[tuple[str, str]], visits: list[tuple[str, str, int, float]]) -> None:
    folder.mkdir(parents=True)
    (folder / "Bookmarks").write_text(json.dumps({"roots": {"bookmark_bar": {"children": [
        {"type": "url", "name": title, "url": url} for title, url in bookmarks]}}}))
    with closing(sqlite3.connect(folder / "History")) as database, database:
        database.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, "
                         "last_visit_time INTEGER, hidden INTEGER DEFAULT 0)")
        for url, title, count, when in visits:
            database.execute("INSERT INTO urls (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?)",
                             (url, title, count, int((when + 11_644_473_600) * 1_000_000)))


class BrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        firefox_profile(self.home / ".mozilla/firefox/abc.default-release",
                        [("Arch Wiki", "https://wiki.archlinux.org/")],
                        [("https://wiki.archlinux.org/title/KDE", "KDE - ArchWiki", 9, NOW - DAY),
                         ("https://kde.org/", "KDE", 2, NOW - 2 * DAY),
                         ("https://old.example.org/kde", "Old KDE page", 50, NOW - 400 * DAY),
                         ("file:///home/user/kde.txt", "kde notes", 30, NOW)])
        firefox_profile(self.home / ".mozilla/firefox/abc.default-release-backup", [("Copy", "https://copy.example/")], [])
        firefox_profile(self.home / ".var/app/org.mozilla.firefox/.mozilla/firefox/xyz.default", [], [
            ("https://store.kde.org/", "KDE Store", 1, NOW - 3 * DAY)])
        chromium_profile(self.home / ".config/chromium/Default", [("KDE", "https://kde.org")],
                         [("https://planet.kde.org/", "Planet KDE", 4, NOW - DAY)])
        self.index = browsers.BrowserIndex(self.home, self.home / ".config")

    def test_profiles_native_flatpak_and_no_copies(self) -> None:
        found = [(profile.browser, profile.folder.name) for profile in browsers.profiles(self.home, self.home / ".config")]
        self.assertEqual(found, [("Firefox", "abc.default-release"), ("Firefox", "xyz.default"), ("Chromium", "Default")])

    def test_search_bookmarks_then_history_by_visits_without_repeats(self) -> None:
        self.index.build(history=True)
        marked, visited = self.index.search("kde", bookmarks=True, history=True)
        self.assertEqual([page.url for page in marked], ["https://kde.org"])
        # kde.org is a bookmark (Chromium), so its Firefox visit is not repeated; old and file: pages are left out.
        self.assertEqual([page.title for page in visited], ["KDE - ArchWiki", "Planet KDE", "KDE Store"])
        self.assertEqual(visited[1].browser, "Chromium")
        self.assertEqual(self.index.search("kde", bookmarks=False, history=True)[0], [])
        self.assertEqual(self.index.search("arch wiki", bookmarks=True, history=False)[0][0].title, "Arch Wiki")

    def test_without_history_switched_on_none_is_read(self) -> None:
        self.index.build(history=False)
        self.assertEqual(self.index.search("planet", bookmarks=True, history=True), ([], []))

    def test_results_open_in_the_browser_and_odd_targets_are_refused(self) -> None:
        self.index.build(history=True)
        with mock.patch.object(quick_results, "_browsers", self.index), \
                mock.patch.object(self.index, "refresh_in_background"):
            results = quick_results.gather("planet kde", [], bookmarks=True, history=True)
            self.assertEqual(quick_results.gather("planet kde", [], bookmarks=False, history=False), [])
        page = next(item for item in results if item["action"]["type"] == "visited")
        self.assertEqual((page["title"], page["subtitle"], page["icon"]),
                         ("Planet KDE", "Visited · planet.kde.org · Chromium", "chromium"))
        started = []
        with mock.patch.object(quick_results, "_start", side_effect=started.append):
            quick_results.activate(page["action"])
            for bad in ("file:///etc/passwd", "javascript:alert(1)", "https://x.org/ --new-window"):
                with self.assertRaises(quick_results.ActivationError):
                    quick_results.activate({"type": "bookmark", "target": bad})
        self.assertEqual(started, [["xdg-open", "https://planet.kde.org/"]])


if __name__ == "__main__":
    unittest.main()
