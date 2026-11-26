"""Tests for offline Wikipedia: finding archives, Kiwix's catalog and downloads, reading, setup and updating.

Nothing here touches the network, the user's archives or their systemd: archives are small files
with Kiwix's names in temporary folders, Kiwix's listing and files are served by a fake
``urlopen``, the reader tool server is a fake ``McpManager``, and unit files go to a temporary
folder without ``systemctl``. The page server is started for real on a loopback port and asked
over HTTP, with a fake archive behind it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import (settings as settings_store, wikipedia_catalog, wikipedia_library,  # noqa: E402
                       wikipedia_reader, wikipedia_routes, wikipedia_setup)
from happy_bot.mcp_client import ToolResult  # noqa: E402

LISTING = """<a href="wikipedia_en_all_maxi_2026-02.zim">wikipedia_en_all_maxi_2026-02.zim</a>   2026-02-26 02:08  115G
<a href="wikipedia_en_all_maxi_2026-08.zim">wikipedia_en_all_maxi_2026-08.zim</a>   2026-09-08 18:38  119G
<a href="wikipedia_en_all_mini_2026-09.zim">wikipedia_en_all_mini_2026-09.zim</a>   2026-09-17 04:44   13G
<a href="wikipedia_en_all_nopic_2026-06.zim">wikipedia_en_all_nopic_2026-06.zim</a>  2026-06-26 09:02   49G
<a href="wikipedia_de_all_mini_2026-10.zim">wikipedia_de_all_mini_2026-10.zim</a>   2026-10-01 01:00  4.4G
<a href="wikipedia_en_all_mini_2026-09.zim.sha256">sha</a>  2026-09-17 04:44   97
"""


def make_archive(folder: Path, name: str, data: bytes = b"zim") -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_archives_are_read_from_kiwix_names_newest_build_first(self) -> None:
        make_archive(self.folder, "wikipedia_en_all_maxi_2026-02.zim")
        make_archive(self.folder, "wikipedia_en_all_maxi_2026-08.zim")
        make_archive(self.folder, "wikipedia_de_all_nopic_2026-10.zim")
        make_archive(self.folder, "stackexchange_en_all_2026-01.zim")
        make_archive(self.folder, "wikipedia_en_all_maxi_2026-09.zim.partial")
        found = wikipedia_library.archives(self.folder)
        self.assertEqual([(a.book, a.build) for a in found], [("wikipedia_en_all_maxi", "2026-08"),
                                                             ("wikipedia_en_all_maxi", "2026-02"),
                                                             ("wikipedia_de_all_nopic", "2026-10")])
        self.assertEqual((found[2].language, found[2].flavour), ("de", "nopic"))
        self.assertEqual(wikipedia_library.archives(self.folder / "missing"), [])

    def test_folders_are_found_from_other_programs_readers_and_standard_places(self) -> None:
        library = self.folder / "zim"
        library.mkdir()
        make_archive(library, "wikipedia_en_all_mini_2026-09.zim")
        empty = self.folder / "empty"
        empty.mkdir()

        class Found:
            command, args = "/usr/bin/openzim-mcp", ("--mode", "advanced", str(library))

        class Other:
            command, args = "/usr/bin/notes-mcp", (str(empty),)

        with mock.patch("happy_bot.mcp_discovery.discover_servers", return_value=[Found(), Other()]), \
                mock.patch("happy_bot.agent_loop.user_folders", return_value={"Downloads": str(empty)}):
            self.assertEqual(wikipedia_library.find_folders({}, self.folder), [os.path.realpath(library)])

    def test_another_programs_updater_or_a_read_only_folder_means_hands_off(self) -> None:
        self.assertEqual(wikipedia_library.updated_elsewhere(str(self.folder)), "")
        (self.folder / wikipedia_library.FOREIGN_LOCK).write_text("")
        self.assertIn("Another program", wikipedia_library.updated_elsewhere(str(self.folder)))
        (self.folder / wikipedia_library.FOREIGN_LOCK).unlink()
        with mock.patch.object(wikipedia_library.os, "access", return_value=False):
            self.assertIn("may not write", wikipedia_library.updated_elsewhere(str(self.folder)))

    def test_settings_group_is_validated_and_a_removed_reader_means_not_set_up(self) -> None:
        self.assertEqual(wikipedia_library.validate_wikipedia({}), wikipedia_library.DEFAULTS)
        for bad in ({"folder": "relative"}, {"auto_update": "yes"}, {"book": "rm -rf"}, {"colour": 1}, []):
            with self.subTest(bad=bad), self.assertRaises(wikipedia_library.WikipediaError):
                wikipedia_library.validate_wikipedia(bad)
        stored = settings_store.validate_settings({"wikipedia": {"server": "gone", "folder": "/srv/zim",
                                                                 "auto_update": True}})
        self.assertEqual((stored["wikipedia"]["server"], stored["wikipedia"]["auto_update"]), ("", False))
        with self.assertRaises(settings_store.SettingsError):
            settings_store.validate_settings({"wikipedia": {"folder": "zim"}})

    def test_the_monthly_timer_exists_only_while_auto_update_is_on(self) -> None:
        units = self.folder / "units"
        on = {"auto_update": True, "book": "wikipedia_en_all_nopic", "folder": str(self.folder)}
        wikipedia_library.sync_timer(on, units, manage=False)
        timer = (units / "happy-bot-wikipedia-update.timer").read_text()
        self.assertIn(f"OnCalendar={wikipedia_library.TIMER_CALENDAR}", timer)
        self.assertIn('"wikipedia" "update"', (units / "happy-bot-wikipedia-update.service").read_text())
        wikipedia_library.sync_timer({**on, "auto_update": False}, units, manage=False)
        self.assertEqual(list(units.iterdir()), [])


class FakeKiwix:
    """Serves the listing, one archive's bytes (with Range), its checksum and its size."""

    def __init__(self, name: str, data: bytes, digest: str | None = None, fail_after: int | None = None) -> None:
        self.name, self.data, self.fail_after = name, data, fail_after
        self.digest = digest or hashlib.sha256(data).hexdigest()
        self.ranges: list[str] = []

    def __call__(self, request, timeout):
        url = request.full_url
        if url.endswith("/wikipedia/"):
            return io.BytesIO(LISTING.replace("wikipedia_en_all_mini_2026-09.zim", self.name).encode())
        if url.endswith(".sha256"):
            return io.BytesIO(f"{self.digest}  {self.name}\n".encode())
        if request.get_method() == "HEAD":
            response = io.BytesIO(b"")
            response.headers = {"Content-Length": str(len(self.data))}
            return response
        start = int(request.headers.get("Range", "bytes=0-")[6:-1] or 0)
        self.ranges.append(request.headers.get("Range", ""))
        body = self.data[start:]
        if self.fail_after is not None:
            body, self.fail_after = body[:self.fail_after], None
        response = io.BytesIO(body)
        response.status = 206 if start else 200
        return response


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        patcher = mock.patch.object(wikipedia_catalog.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_listing_gives_the_newest_build_of_each_size_smallest_first(self) -> None:
        offered = wikipedia_catalog.parse_listing(LISTING, "en")
        self.assertEqual([(item["flavour"], item["build"]) for item in offered],
                         [("mini", "2026-09"), ("nopic", "2026-06"), ("maxi", "2026-08")])
        self.assertEqual(offered[2]["size"], 119 * 1024**3)
        self.assertEqual(wikipedia_catalog.parse_listing(LISTING, "de")[0]["size"], int(4.4 * 1024**3))

    def test_a_newer_build_is_downloaded_checked_put_in_place_and_the_old_one_removed(self) -> None:
        old = make_archive(self.folder, "wikipedia_en_all_mini_2026-06.zim")
        kiwix = FakeKiwix("wikipedia_en_all_mini_2026-09.zim", b"x" * 3000, fail_after=1000)
        progress = wikipedia_catalog.Progress()
        with mock.patch.object(wikipedia_catalog.urllib.request, "urlopen", side_effect=kiwix), \
                mock.patch.object(wikipedia_catalog, "CHUNK", 512):
            result = wikipedia_catalog.update(self.folder, "wikipedia_en_all_mini", progress)
        self.assertEqual(result, {"action": "downloaded", "file": kiwix.name, "removed": [old.name]})
        self.assertEqual((self.folder / kiwix.name).read_bytes(), kiwix.data)
        self.assertEqual(kiwix.ranges, ["", "bytes=1000-"])  # resumed after the interruption
        self.assertEqual(progress.snapshot()["done_bytes"], 3000)
        with mock.patch.object(wikipedia_catalog.urllib.request, "urlopen", side_effect=kiwix):
            self.assertEqual(wikipedia_catalog.update(self.folder, "wikipedia_en_all_mini")["action"], "current")

    def test_a_wrong_checksum_deletes_the_download_and_keeps_the_old_archive(self) -> None:
        old = make_archive(self.folder, "wikipedia_en_all_mini_2026-06.zim")
        kiwix = FakeKiwix("wikipedia_en_all_mini_2026-09.zim", b"y" * 100, digest="0" * 64)
        with mock.patch.object(wikipedia_catalog.urllib.request, "urlopen", side_effect=kiwix), \
                self.assertRaisesRegex(wikipedia_catalog.CatalogError, "checksum"):
            wikipedia_catalog.update(self.folder, "wikipedia_en_all_mini")
        self.assertTrue(old.exists())
        self.assertEqual([path.name for path in self.folder.iterdir() if path.suffix != ".lock"], [old.name])

    def test_too_little_space_and_a_second_run_are_refused(self) -> None:
        kiwix = FakeKiwix("wikipedia_en_all_mini_2026-09.zim", b"z" * 100)
        with mock.patch.object(wikipedia_catalog.urllib.request, "urlopen", side_effect=kiwix), \
                mock.patch.object(wikipedia_catalog.shutil, "disk_usage", return_value=mock.Mock(free=10)), \
                self.assertRaisesRegex(wikipedia_catalog.CatalogError, "free space"):
            wikipedia_catalog.update(self.folder, "wikipedia_en_all_mini")
        import fcntl
        with (self.folder / wikipedia_library.OWN_LOCK).open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with mock.patch.object(wikipedia_catalog.urllib.request, "urlopen", side_effect=kiwix):
                self.assertEqual(wikipedia_catalog.update(self.folder, "wikipedia_en_all_mini"), {"action": "busy"})


ARTICLE_HTML = """<html><head><title>T</title><style>p{}</style></head><body class="vector-toc-available">
<h1>Eiffel Tower</h1><section><div class="hatnote">For other uses see X.</div>
<table class="infobox"><tr><td>Height 330 m</td></tr></table>
<p>The <b>Eiffel Tower</b> is a <a rel="mw:WikiLink" href="Lattice_tower">lattice tower</a> in
<a href="./Paris">Paris</a>.<sup class="reference"><a href="#cite_note-1">[1]</a></sup> It is <i>tall</i>.</p>
<h2>History</h2><ul><li>Built <a href="https://example.org/x">1889</a></li><li></li></ul>
<div class="navbox"><a href="Other">navigation</a></div>
<div class="catlinks">Categories: Towers</div></section></body></html>"""


class FakeManager:
    def __init__(self, replies: dict[str, object]) -> None:
        self.replies, self.calls = replies, []

    def call_tool(self, server, tool, arguments, timeout):
        self.calls.append((server, tool, arguments))
        reply = self.replies[tool if tool != "zim_search" else f"zim_search:{arguments.get('mode', 'fulltext')}"]
        return ToolResult(json.dumps(reply))


class ReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.archive = make_archive(self.folder, "wikipedia_en_all_nopic_2026-06.zim")
        self.settings = {"wikipedia": {"server": "wikipedia", "folder": str(self.folder),
                                       "book": "wikipedia_en_all_nopic", "auto_update": False}}

    def test_articles_become_clean_light_markdown(self) -> None:
        text, cut = wikipedia_reader.clean_article(ARTICLE_HTML)
        self.assertFalse(cut)
        self.assertEqual(text, "The **Eiffel Tower** is a [lattice tower](Lattice_tower) in [Paris](Paris). It is "
                               "*tall*.\n\n## History\n\n- Built [1889](https://example.org/x)")
        with mock.patch.object(wikipedia_reader, "MAX_ARTICLE_CHARS", 40):
            self.assertTrue(wikipedia_reader.clean_article(ARTICLE_HTML)[1])

    def test_link_targets_keep_articles_and_web_addresses_only(self) -> None:
        cases = {"Paris": "Paris", "./Windsor%2C_Ontario#History": "Windsor%2C_Ontario", "#cite_note-1": "",
                 "https://example.org": "https://example.org", "Category%3AX": "Category%3AX", "/w/x": "",
                 "geo:42,-83": "", "Python_(language)": "Python_%28language%29"}
        for href, target in cases.items():
            with self.subTest(href=href):
                self.assertEqual(wikipedia_reader._link_target(href), target)

    def test_search_puts_the_exact_title_first_and_skips_category_pages(self) -> None:
        manager = FakeManager({
            "zim_search:title": {"results": [{"path": "Python", "title": "Python"}]},
            "zim_search:fulltext": {"results": [
                {"path": "Python_(programming_language)", "title": "Python (programming language)",
                 "snippet": "**Python** is a [language](Language)"},
                {"path": "Category:Pythons", "title": "Category:Pythons", "snippet": ""},
                {"path": "Python", "title": "Python", "snippet": "A snake"}]}})
        hits = wikipedia_reader.search(manager, self.settings, "python")
        self.assertEqual([(hit["title"], hit["snippet"]) for hit in hits],
                         [("Python", "A snake"), ("Python (programming language)", "Python is a language")])
        self.assertEqual({call[2]["zim_file_path"] for call in manager.calls}, {str(self.archive)})

    def test_entries_wait_and_retry_when_the_reader_is_rate_limited(self) -> None:
        busy = {"error": "rate_limited", "message": "Rate limit exceeded for operation 'get_binary_entry'. "
                                                     "Please wait 0.11 seconds before retrying."}
        replies = [busy, {"mime_type": "image/png", "data": base64.b64encode(b"img").decode()}]

        class Manager:
            def call_tool(self, server, tool, arguments, timeout):
                return ToolResult(json.dumps(replies.pop(0)))

        with mock.patch.object(wikipedia_reader.time, "sleep") as slept:
            self.assertEqual(wikipedia_reader.entry(Manager(), self.settings, "_assets_/x.png"), (b"img", "image/png"))
        slept.assert_called_once()
        replies[:] = [busy] * 5
        with mock.patch.object(wikipedia_reader.time, "sleep"), self.assertRaisesRegex(wikipedia_reader.ReaderError, "Rate"):
            wikipedia_reader.entry(Manager(), self.settings, "_assets_/x.png")

    def test_an_article_is_fetched_raw_and_cleaned_and_problems_are_plain(self) -> None:
        manager = FakeManager({"zim_get": {"path": "Eiffel_Tower", "title": "Eiffel Tower", "mime_type": "text/html",
                                           "data": base64.b64encode(ARTICLE_HTML.encode()).decode()}})
        article = wikipedia_reader.article(manager, self.settings, "Eiffel%20Tower_%28x%29")
        self.assertEqual(manager.calls[0][2]["entry_path"], "Eiffel Tower_(x)")
        self.assertEqual((article["title"], article["text"][:16]), ("Eiffel Tower", "The **Eiffel Tow"))
        self.assertTrue(manager.calls[0][2]["binary"])
        with self.assertRaisesRegex(wikipedia_reader.ReaderError, "not set up"):
            wikipedia_reader.search(manager, {"wikipedia": {**self.settings["wikipedia"], "server": ""}}, "x")
        with self.assertRaisesRegex(wikipedia_reader.ReaderError, "not set up"):
            wikipedia_reader.current_archive({"wikipedia": {"folder": str(self.folder / "none")}})
        broken = FakeManager({"zim_get": {"error": "entry_not_found", "message": "No such article"}})
        with self.assertRaisesRegex(wikipedia_reader.ReaderError, "No such article"):
            wikipedia_reader.article(broken, self.settings, "Nope")


class PageServerTests(unittest.TestCase):
    def setUp(self) -> None:
        from happy_bot import wikipedia_pages
        self.asked = []

        def fetch(entry):
            self.asked.append(entry)
            if entry == "Eiffel_Tower":
                return b"<html><head><title>Eiffel Tower</title></head><body>x</body></html>", "text/html"
            if entry.startswith("_assets_/"):
                return b"\x89PNG", "image/png"
            raise wikipedia_reader.ReaderError("not there")

        self.pages = wikipedia_pages.PageServer(fetch)
        self.addCleanup(self.pages.close)

    def get(self, url, host=None):
        import urllib.error
        import urllib.request
        request = urllib.request.Request(url, headers={"Host": host} if host else {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, {}, b""

    def test_pages_are_served_under_the_secret_with_the_fit_style_and_a_strict_policy(self) -> None:
        url = self.pages.url("Eiffel_Tower")
        self.assertTrue(url.startswith("http://127.0.0.1:") and f"/{self.pages.token}/" in url)
        status, headers, body = self.get(url)
        self.assertEqual(status, 200)
        self.assertIn(b'<style id="happy-bot-fit">', body)
        self.assertLess(body.index(b"happy-bot-fit"), body.index(b"</head>"))
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        status, headers, body = self.get(url.rsplit("/", 1)[0] + "/_assets_/a/Center%252C_Detroit.png")
        self.assertEqual((status, body), (200, b"\x89PNG"))
        self.assertEqual(self.asked[-1], "_assets_/a/Center%2C_Detroit.png")  # decoded once, as the archive names it

    def test_wrong_secret_wrong_host_and_missing_entries_are_refused(self) -> None:
        url = self.pages.url("Eiffel_Tower")
        self.assertEqual(self.get(url.replace(self.pages.token, "guess"))[0], 404)
        self.assertEqual(self.get(url, host="evil.example")[0], 404)
        self.assertEqual(self.get(url.rsplit("/", 1)[0] + "/Nowhere")[0], 404)


class FakeServer:
    def __init__(self, folder: Path) -> None:
        self.settings = settings_store.validate_settings({})
        self.mcp = mock.Mock()
        self.wikipedia_download = wikipedia_setup.DownloadJob()
        self.folder = folder

    def replace_settings(self, new):
        self.settings = settings_store.validate_settings(new)
        return self.settings


class SetupTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "zim"
        self.folder.mkdir()
        make_archive(self.folder, "wikipedia_en_all_maxi_2026-08.zim")
        self.server = FakeServer(self.folder)
        for patcher in (mock.patch.object(wikipedia_library, "find_folders", return_value=[str(self.folder)]),
                        mock.patch.object(wikipedia_setup, "_test"),
                        mock.patch.object(wikipedia_setup.shutil, "which",
                                          side_effect=lambda name: "/usr/bin/uvx" if name == "uvx" else None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_choices_offer_found_archives_and_the_sizes_that_fit(self) -> None:
        with mock.patch.object(wikipedia_catalog, "available", return_value=wikipedia_catalog.parse_listing(LISTING, "en")), \
                mock.patch.object(wikipedia_library, "free_space", return_value=60 * 1024**3):
            offered = wikipedia_setup.choices(self.server.settings)
        self.assertEqual(offered["found"][0]["id"], f"folder:{self.folder}")
        self.assertEqual([(item["flavour"], item["fits"]) for item in offered["downloads"]],
                         [("mini", True), ("nopic", True), ("maxi", False)])
        self.assertFalse(any(item["recommended"] for item in offered["downloads"]))  # an archive is already here
        with mock.patch.object(wikipedia_library, "find_folders", return_value=[]), \
                mock.patch.object(wikipedia_catalog, "available", return_value=wikipedia_catalog.parse_listing(LISTING, "en")), \
                mock.patch.object(wikipedia_library, "free_space", return_value=60 * 1024**3):
            self.assertEqual([item["flavour"] for item in wikipedia_setup.choices({})["downloads"] if item["recommended"]],
                             ["nopic"])

    def test_using_a_found_folder_adds_a_read_only_reader_and_respects_another_updater(self) -> None:
        (self.folder / wikipedia_library.FOREIGN_LOCK).write_text("")
        result = wikipedia_setup.use(self.server, f"folder:{self.folder}", auto_update=True)
        self.assertTrue(result["ok"], result)
        entry = self.server.settings["tool_servers"]["wikipedia"]
        self.assertEqual((entry["command"], entry["args"][-3:], entry["read_only"], entry["tools"]),
                         ("uvx", ["--mode", "advanced", str(self.folder)], True, wikipedia_setup.AI_TOOLS))
        self.assertIn(f"openzim-mcp=={wikipedia_setup.READER_VERSION}", entry["args"])
        self.assertEqual(entry["env"], wikipedia_setup.READER_ENV)  # whole pages need bursts of reads
        self.assertEqual(self.server.settings["wikipedia"], {"server": "wikipedia", "folder": str(self.folder),
                                                             "book": "wikipedia_en_all_maxi", "auto_update": False})
        self.assertFalse(wikipedia_setup.set_auto_update(self.server, True)["ok"])
        self.assertTrue(wikipedia_setup.status(self.server)["set_up"])
        off = wikipedia_setup.turn_off(self.server)
        self.assertIn(str(self.folder), off["message"])
        self.assertNotIn("wikipedia", self.server.settings["tool_servers"])
        self.assertTrue((self.folder / "wikipedia_en_all_maxi_2026-08.zim").exists())

    def test_a_failing_reader_changes_nothing_and_unknown_choices_are_refused(self) -> None:
        before = self.server.settings
        with mock.patch.object(wikipedia_setup, "_test", side_effect=wikipedia_setup.SetupError("would not start")):
            self.assertEqual(wikipedia_setup.use(self.server, f"folder:{self.folder}", False),
                             {"ok": False, "error": "would not start"})
        self.assertEqual(self.server.settings, before)
        self.assertFalse(wikipedia_setup.use(self.server, "folder:/elsewhere", False)["ok"])
        self.assertFalse(wikipedia_setup.use(self.server, "magic:x", False)["ok"])

    def test_a_download_runs_in_the_background_then_sets_it_up(self) -> None:
        own = Path(self.folder.parent / "own")
        done = threading.Event()

        def fake_update(folder, book, progress, cancel):
            make_archive(Path(folder), f"{book}_2026-06.zim")
            return {"action": "downloaded"}

        def finished(*args, **kwargs):
            done.set()
            return original_apply(*args, **kwargs)

        original_apply = wikipedia_setup._apply
        with mock.patch.object(wikipedia_library, "own_folder", return_value=own), \
                mock.patch.object(wikipedia_catalog, "update", side_effect=fake_update), \
                mock.patch.object(wikipedia_setup, "_apply", side_effect=finished):
            own.mkdir()
            result = wikipedia_setup.use(self.server, "download:wikipedia_en_all_nopic", True)
            self.assertTrue(result["started"])
            self.assertTrue(done.wait(5))
            self.server.wikipedia_download._thread.join(5)
        self.assertEqual(self.server.wikipedia_download.progress.snapshot()["state"], "done")
        self.assertEqual((self.server.settings["wikipedia"]["book"], self.server.settings["wikipedia"]["auto_update"]),
                         ("wikipedia_en_all_nopic", True))

    def test_the_timer_job_updates_only_what_happy_bot_keeps(self) -> None:
        kept = {"wikipedia": {"server": "w", "folder": str(self.folder), "book": "wikipedia_en_all_maxi",
                              "auto_update": True}}
        self.assertEqual(wikipedia_setup.scheduled_update({"wikipedia": {**kept["wikipedia"], "auto_update": False}}),
                         {"ok": True, "action": "off"})
        with mock.patch.object(wikipedia_catalog, "update", return_value={"action": "current"}) as update:
            self.assertEqual(wikipedia_setup.scheduled_update(kept), {"ok": True, "action": "current"})
            update.assert_called_once_with(str(self.folder), "wikipedia_en_all_maxi")
        (self.folder / wikipedia_library.FOREIGN_LOCK).write_text("")
        self.assertEqual(wikipedia_setup.scheduled_update(kept)["action"], "updated_elsewhere")


class SelfCheckTests(unittest.TestCase):
    def test_a_missing_archive_and_a_failed_download_are_reported_with_a_fix(self) -> None:
        from happy_bot import self_check
        server = FakeServer(Path("/nowhere"))
        self.assertEqual(self_check._wikipedia(server), [])
        server.settings = {**server.settings, "wikipedia": {"server": "wikipedia", "folder": "/nowhere"}}
        server.wikipedia_download.progress.set(state="failed", message="Not enough free space")
        checks = self_check._wikipedia(server)
        self.assertEqual([(check["name"], check["ok"]) for check in checks],
                         [("Offline Wikipedia", False), ("Offline Wikipedia download", False)])
        self.assertIn("Set up", checks[0]["fix"])


class RouteTests(unittest.TestCase):
    def test_routes_report_not_set_up_and_reader_failures_with_their_codes(self) -> None:
        server = FakeServer(Path("/nowhere"))
        status, reply = wikipedia_routes.search(server, {"q": ["eiffel"]}, {})
        self.assertEqual((status, reply["code"]), (409, "not_configured"))
        self.assertEqual(wikipedia_routes.search(server, {"q": [""]}, {})[1]["hits"], [])
        with mock.patch.object(wikipedia_reader, "article", side_effect=wikipedia_reader.ReaderError("did not answer")):
            self.assertEqual(wikipedia_routes.article(server, {"path": ["X"]}, {})[1]["code"], "tool_failed")
        self.assertEqual(wikipedia_routes.status(server, {}, {})[1]["set_up"], False)
        self.assertEqual(wikipedia_routes.page(server, {"path": ["Eiffel_Tower"]}, {})[1]["code"], "not_configured")
        self.assertEqual(wikipedia_routes.page(server, {}, {})[0], 400)


if __name__ == "__main__":
    unittest.main()
