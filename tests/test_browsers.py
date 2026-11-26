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
                               "CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER, title TEXT);"
                               "CREATE TABLE moz_historyvisits (place_id INTEGER, visit_date INTEGER);")
        for title, url in bookmarks:
            place = database.execute("INSERT INTO moz_places (url, title, visit_count) VALUES (?, ?, 0)", (url, title)).lastrowid
            database.execute("INSERT INTO moz_bookmarks (type, fk, title) VALUES (1, ?, ?)", (place, title))
        for url, title, count, when in visits:
            timestamp = int(when * 1_000_000)
            place = database.execute("INSERT INTO moz_places (url, title, visit_count, last_visit_date) VALUES (?, ?, ?, ?)",
                                     (url, title, count, timestamp)).lastrowid
            database.executemany("INSERT INTO moz_historyvisits VALUES (?, ?)", [(place, timestamp)] * count)


def chromium_profile(folder: Path, bookmarks: list[tuple[str, str]], visits: list[tuple[str, str, int, float]]) -> None:
    folder.mkdir(parents=True)
    (folder / "Bookmarks").write_text(json.dumps({"roots": {"bookmark_bar": {"children": [
        {"type": "url", "name": title, "url": url} for title, url in bookmarks]}}}))
    with closing(sqlite3.connect(folder / "History")) as database, database:
        database.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, "
                         "last_visit_time INTEGER, hidden INTEGER DEFAULT 0)")
        database.execute("CREATE TABLE visits (url INTEGER, visit_time INTEGER)")
        for url, title, count, when in visits:
            timestamp = int((when + 11_644_473_600) * 1_000_000)
            place = database.execute("INSERT INTO urls (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?)",
                                     (url, title, count, timestamp)).lastrowid
            database.executemany("INSERT INTO visits VALUES (?, ?)", [(place, timestamp)] * count)


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

    def test_ladybird_profile_supplies_bookmarks_history_and_favicons(self) -> None:
        data = self.home / "custom-data"
        profile = data / "Ladybird/Profiles/default"
        profile.mkdir(parents=True)
        config = self.home / ".config/Ladybird/Profiles/default"
        config.mkdir(parents=True)
        (config / "Bookmarks.json").write_text(json.dumps({"version": 2, "items": [
            {"type": "folder", "children": [
                {"type": "bookmark", "url": "https://docs.example/", "title": "Ladybird docs"}]}
        ]}), encoding="utf-8")
        with closing(sqlite3.connect(profile / "History.db")) as db, db:
            db.executescript("""
                CREATE TABLE History (url, title, visit_count, last_visited_time, favicon_hash);
                CREATE TABLE Favicons (hash, png_data);
            """)
            db.execute("INSERT INTO History VALUES ('https://bird.example/page', 'Ladybird page', 7, ?, 'icon')",
                       (int(NOW - DAY),))
            db.execute("INSERT INTO Favicons VALUES ('icon', ?)", (b"\x89PNG\r\n\x1a\n",))
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(data)}):
            self.index.build(history=False)
            bookmarked, visited = self.index.search("Ladybird", bookmarks=True, history=False)
            self.assertEqual([page.title for page in bookmarked], ["Ladybird docs"])
            self.assertEqual(visited, [])
            self.index.build(history=True)
            _, visited = self.index.search("Ladybird", bookmarks=False, history=True)
            self.assertEqual([(page.browser, page.visits) for page in visited], [("Ladybird", 7)])
            site = next(row for row in self.index.frequent_sites() if row["host"] == "bird.example")
            self.assertEqual(self.index.favicons([site])["bird.example"], "data:image/png;base64,iVBORw0KGgo=")
            cleared = browsers.BrowserIndex(self.home, self.home / ".config", history_since=NOW - DAY / 2)
            self.assertFalse(any(row["host"] == "bird.example" for row in cleared.frequent_sites()))

    def test_website_icons_come_from_the_local_browser_caches(self) -> None:
        firefox = self.home / ".mozilla/firefox/abc.default-release/favicons.sqlite"
        chromium = self.home / ".config/chromium/Default/Favicons"
        png = b"\x89PNG\r\n\x1a\n"
        with closing(sqlite3.connect(firefox)) as db, db:
            db.executescript("""
                CREATE TABLE moz_pages_w_icons (id, page_url);
                CREATE TABLE moz_icons_to_pages (page_id, icon_id);
                CREATE TABLE moz_icons (id, width, icon_url, root, data);
                INSERT INTO moz_icons_to_pages VALUES (1, 1);
                INSERT INTO moz_pages_w_icons VALUES (1, 'https://www.kde.org/download/');
            """)
            db.execute("INSERT INTO moz_icons VALUES (1, 32, 'https://kde.org/icon.png', 0, ?)", (png,))
        with closing(sqlite3.connect(chromium)) as db, db:
            db.executescript("""
                CREATE TABLE icon_mapping (page_url, icon_id);
                CREATE TABLE favicon_bitmaps (icon_id, width, image_data);
                INSERT INTO icon_mapping VALUES ('https://planet.kde.org/', 1);
            """)
            db.execute("INSERT INTO favicon_bitmaps VALUES (1, 48, ?)", (png,))
        sites = [{"host": host, "location": f"https://{host}/"}
                 for host in ("kde.org", "planet.kde.org", "missing.example")]
        icons = self.index.favicons(sites)
        self.assertEqual(icons, {site["host"]: "data:image/png;base64,iVBORw0KGgo=" for site in sites[:2]})

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

    def test_frequent_sites_rank_hosts_and_keep_only_homepages(self) -> None:
        chromium_profile(self.home / ".config/chromium/Profile 1", [],
                         [("https://www.kde.org/private?key=secret", "A private page title", 8, NOW - DAY),
                          ("https://user:password@private.example/", "Credentials", 50, NOW),
                          ("https://other.example/account", "Another private page title", 1, NOW),
                          ("https://wiki.archlinux.org:8443/page", "Another service", 1, NOW - 2 * DAY)])
        rows = self.index.frequent_sites()  # first opening builds the history index
        self.assertEqual([row["host"] for row in rows], ["kde.org", "wiki.archlinux.org", "planet.kde.org",
                                                        "other.example", "wiki.archlinux.org:8443", "store.kde.org"])
        self.assertEqual(rows[0], {"host": "kde.org", "title": "KDE", "location": "https://www.kde.org/"})
        self.assertEqual(rows[1]["title"], "wiki.archlinux.org")
        self.assertNotIn("private", json.dumps(rows))
        self.assertNotIn("secret", json.dumps(rows))
        with mock.patch.object(browsers, "profiles", side_effect=AssertionError("already indexed")):
            self.assertEqual(self.index.frequent_sites(), rows)

    def test_after_clear_old_visits_to_a_revisited_site_do_not_affect_its_rank(self) -> None:
        firefox = self.home / ".mozilla/firefox/abc.default-release/places.sqlite"
        with closing(sqlite3.connect(firefox)) as database, database:
            database.execute("UPDATE moz_historyvisits SET visit_date = ?", (int((NOW - 10 * DAY) * 1e6),))
            database.execute("INSERT INTO moz_historyvisits SELECT id, last_visit_date FROM moz_places WHERE visit_count > 0")
        index = browsers.BrowserIndex(self.home, self.home / ".config", history_since=NOW - 1.5 * DAY)
        self.assertEqual([row["host"] for row in index.frequent_sites()], ["planet.kde.org", "wiki.archlinux.org"])

    def test_rebuilding_after_a_clear_keeps_bookmarks_and_only_later_visits(self) -> None:
        database = self.home / ".mozilla/firefox/abc.default-release/places.sqlite"
        original = database.read_bytes()
        index = browsers.BrowserIndex(self.home, self.home / ".config", history_since=NOW - 1.5 * DAY)
        index.build(history=True)
        bookmarks, visited = index.search("kde", bookmarks=True, history=True)
        self.assertEqual([page.title for page in bookmarks], ["KDE"])
        self.assertEqual([page.title for page in visited], ["KDE - ArchWiki", "Planet KDE"])
        self.assertEqual(database.read_bytes(), original)

    def test_results_open_in_the_browser_and_odd_targets_are_refused(self) -> None:
        self.index.build(history=True)
        with mock.patch.object(quick_results, "_browsers", self.index), \
                mock.patch.object(self.index, "refresh_in_background"):
            results = quick_results.gather("planet kde", [], bookmarks=True, history=True)
            self.assertEqual(quick_results.gather("planet kde", [], bookmarks=False, history=False), [])
        page = next(item for item in results if item["action"]["type"] == "visited")
        self.assertEqual(page["site_host"], "planet.kde.org")
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
