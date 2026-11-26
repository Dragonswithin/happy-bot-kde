"""Preferences and session search history behind the web finder's start page."""
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import isolation  # noqa: E402,F401
from happy_bot import web_preferences as web  # noqa: E402
from happy_bot.daemon_http import AssistantServer  # noqa: E402
from happy_bot.quick_results import SearchHistory  # noqa: E402
from happy_bot.settings import load_settings  # noqa: E402
from happy_bot.ui_settings import UiSettingsError, validate_ui  # noqa: E402


class WebSiteTests(unittest.TestCase):
    def test_homepage_identity_and_validation(self):
        for url in ("file:///etc/", "https://user:pass@example.com/", "https://host:abc/",
                    "http://host\\evil/", "https://a bad.host", "https://[oops", None):
            self.assertIsNone(web.site_identity(url))
        self.assertEqual(web.site_identity("https://WWW.Example.com:443/private?q=hidden#x"),
                         ("example.com", "https://www.example.com/"))
        self.assertEqual(web.site_identity("http://[::1]:8080/a"), ("[::1]:8080", "http://[::1]:8080/"))
        self.assertEqual(web.site_identity("https://bücher.example/a"),
                         ("xn--bcher-kva.example", "https://xn--bcher-kva.example/"))
        with self.assertRaises(UiSettingsError):
            validate_ui({"web_hidden": ["https://example.org"], "web_pins": ["http://www.example.org"]})

    def test_pins_survive_ranking_and_hidden_sites_can_be_restored(self):
        ui = validate_ui({})
        urls = [f"https://s{i}.example/" for i in range(12)]
        ranked = [dict(host=web.site_identity(url)[0], title="A site", location=url) for url in urls]
        ui.update(web.changed_sites(ui, urls[-1], "pin"))
        ui.update(web.changed_sites(ui, urls[0], "hide"))
        rows = web.site_rows(ranked, ui)
        self.assertEqual(len(rows), web.SITE_COUNT)
        self.assertEqual((rows[0]["location"], rows[0]["pinned"]), (urls[-1], True))
        self.assertNotIn(urls[0], [row["location"] for row in rows])
        ui.update(web.changed_sites(ui, urls[0], "unhide"))
        self.assertEqual(web.site_rows(ranked, ui)[1]["location"], urls[0])
        ui.update(web.changed_sites(ui, urls[-1], "unpin"))
        self.assertEqual(web.site_rows([], ui), [])
        for url in urls:
            ui.update(web.changed_sites(ui, url, "pin"))
        self.assertEqual([row["location"] for row in web.site_rows([], ui)], urls)

    def test_simultaneous_pins_and_ui_edits_survive_in_the_settings_file(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config = base / "settings.json"
            server = AssistantServer("127.0.0.1", 0, base / "runtime", config, base / "chats")
            try:
                with ThreadPoolExecutor(max_workers=5) as pool:
                    futures = [pool.submit(server.change_web_site, f"https://s{i}.example/private", "pin") for i in range(6)]
                    futures.append(pool.submit(server.update_ui, {"floating_opacity": 63}))
                    for future in futures:
                        future.result()
                ui = load_settings(config)["ui"]
                self.assertCountEqual(ui["web_pins"], [f"https://s{i}.example/" for i in range(6)])
                self.assertEqual(ui["floating_opacity"], 63)
            finally:
                server.shutdown_tools()
                server.server_close()


class RecentWebSearchTests(unittest.TestCase):
    def test_runtime_history_restarts_clears_and_ignores_late_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            marker, queries = Path(folder) / "cutoff", Path(folder) / "queries"
            history = SearchHistory(marker, queries)
            history.remember_web_query("KDE keyboard shortcuts", 0)
            history.remember_web_query("other query", 0)
            history.remember_web_query("  KDE   Keyboard shortcuts  ", 0)
            self.assertEqual(queries.stat().st_mode & 0o777, 0o600)
            history = SearchHistory(marker, queries)
            self.assertEqual(history.web_queries(), ["KDE Keyboard shortcuts", "other query"])
            old_data = queries.read_bytes()
            with mock.patch("happy_bot.quick_results.write_private_file", side_effect=OSError):
                with self.assertRaises(OSError):
                    history.clear()
            self.assertEqual(history.web_queries()[0], "KDE Keyboard shortcuts")
            history.clear()
            self.assertFalse(queries.exists())
            history.remember_web_query("delayed old search", 0)
            self.assertEqual(history.web_queries(), [])
            queries.write_bytes(old_data)  # Even a stale runtime file cannot restore a cleared query.
            history = SearchHistory(marker, queries)
            self.assertEqual(history.web_queries(), [])
            history.remember_web_query("new search", history.index.history_since)
            self.assertEqual(history.web_queries(), ["new search"])
