"""Tests for the finding tools and the "local only" setting.

Recent files and bookmarks are read from files written into a temporary home;
web pages are parsed from fixed HTML, and the address checks run without a
network request (private and loopback addresses are refused before any
fetch). The catalogue test checks that "local only" removes the web tools.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.mcp_client import McpManager  # noqa: E402
from happy_bot.settings import validate_settings  # noqa: E402
from happy_bot.tools import catalog, finding  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402


class FindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        patcher = mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.home / "data"),
                                               "XDG_CONFIG_HOME": str(self.home / "config"), "HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recent_files_newest_first_and_filtered(self) -> None:
        (self.home / "data").mkdir()
        kept = self.home / "invoice.pdf"
        kept.write_text("x")
        (self.home / "data" / "recently-used.xbel").write_text(
            '<?xml version="1.0"?><xbel version="1.0">'
            f'<bookmark href="file://{kept}" modified="2026-11-20T10:00:00Z"/>'
            '<bookmark href="file:///gone/report%20draft.odt" modified="2026-11-22T09:00:00Z"/>'
            '<bookmark href="https://example.com" modified="2026-11-23T09:00:00Z"/></xbel>')
        lines = finding.recent_files({}).splitlines()
        self.assertEqual(lines[0], "2026-11-22 09:00  /gone/report draft.odt  (no longer there)")
        self.assertIn(str(kept), lines[1])
        self.assertEqual(len(lines), 2)
        self.assertIn("invoice", finding.recent_files({"contains": "INVOICE"}))

    def test_bookmarks_from_chromium_and_firefox(self) -> None:
        chromium = self.home / "config" / "chromium" / "Default"
        chromium.mkdir(parents=True)
        (chromium / "Bookmarks").write_text(json.dumps({"roots": {"bookmark_bar": {"children": [
            {"type": "url", "name": "KDE Store", "url": "https://store.kde.org"},
            {"type": "folder", "children": [{"type": "url", "name": "Arch Wiki", "url": "https://wiki.archlinux.org"}]}]}}}))
        profile = self.home / ".mozilla" / "firefox" / "abc.default"
        profile.mkdir(parents=True)
        with sqlite3.connect(profile / "places.sqlite") as database:
            database.executescript("CREATE TABLE moz_places (id INTEGER, url TEXT);"
                                   "CREATE TABLE moz_bookmarks (fk INTEGER, title TEXT, type INTEGER);"
                                   "INSERT INTO moz_places VALUES (1, 'https://kde.org');"
                                   "INSERT INTO moz_bookmarks VALUES (1, 'KDE home', 1);")
        text = finding.browser_bookmarks({"contains": "kde"})
        self.assertIn("KDE Store  https://store.kde.org  [Chromium]", text)
        self.assertIn("KDE home  https://kde.org  [Firefox]", text)
        self.assertIn("Arch Wiki", finding.browser_bookmarks({"contains": "arch wiki"}))

    def test_page_text_keeps_content_and_drops_scripts(self) -> None:
        title, text = finding.page_text("<html><head><title>News</title><script>var x=1</script></head>"
                                        "<body><nav>Menu</nav><h1>Big story</h1><p>First &amp; second.</p></body></html>")
        self.assertEqual(title, "News")
        self.assertEqual(text, "Big story\nFirst & second.")

    def test_private_and_odd_addresses_are_refused(self) -> None:
        for url in ("http://127.0.0.1:19000/health", "http://localhost/", "http://192.168.1.10/", "file:///etc/passwd",
                    "ftp://example.com/x"):
            with self.subTest(url=url), self.assertRaises(ToolFailure):
                finding.read_web_page({"url": url})

    def test_local_only_removes_web_tools(self) -> None:
        names = catalog.build_registry(McpManager(), validate_settings({"agent": {"local_only": True}}))[0].names()
        self.assertNotIn("read_web_page", names)
        self.assertIn("recent_files", names)
        self.assertIn("read_web_page", catalog.build_registry(McpManager(), validate_settings({}))[0].names())


if __name__ == "__main__":
    unittest.main()
