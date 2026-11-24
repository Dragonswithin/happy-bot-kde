"""Tests for one-press search setup: the built-in file-index server, the choices offered, and using one.

``file_index_server`` is driven through its JSON-RPC ``handle`` with the index programs replaced by
fakes. ``search_choices`` runs with discovery, program lookups and the SearXNG probe faked, so no
server starts and no port is probed. ``search_setup.use`` runs against a stand-in daemon whose
``replace_settings`` validates with the real settings schema; the first start and the test search
are faked, so nothing is downloaded and the user's settings are never touched.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import file_index_server, search_choices, search_setup  # noqa: E402
from happy_bot.mcp_client import McpError, ToolResult  # noqa: E402
from happy_bot.settings import default_settings, validate_settings  # noqa: E402

HOME = "/home/someone"


class FileIndexServerTests(unittest.TestCase):
    def call(self, index: str, arguments: dict[str, Any]) -> dict[str, Any]:
        message = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "find_files", "arguments": arguments}}
        return file_index_server.handle(message, index)["result"]

    def test_lists_one_tool_and_ignores_notifications(self) -> None:
        listed = file_index_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "kde")
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], ["find_files"])
        self.assertIsNone(file_index_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, "kde"))

    def test_results_stay_in_home_skip_hidden_and_rank_whole_names_first(self) -> None:
        found = [f"{HOME}/Documents/old/tax-notes.txt", "/usr/share/doc/tax.txt", f"{HOME}/.cache/tax.bin",
                 f"{HOME}/node_modules/tax/index.js", f"{HOME}/Documents/tax return 2025.pdf"]
        with mock.patch.object(file_index_server.shutil, "which", return_value="/usr/bin/plocate"), \
                mock.patch.object(file_index_server, "_lines", return_value=found), \
                mock.patch.object(file_index_server.Path, "home", return_value=Path(HOME)):
            result = self.call("locate", {"query": "tax return", "limit": 5})
        paths = [item["path"] for item in json.loads(result["content"][0]["text"])["results"]]
        self.assertEqual(paths, [f"{HOME}/Documents/tax return 2025.pdf", f"{HOME}/Documents/old/tax-notes.txt"])

    def test_a_missing_index_is_a_tool_error_with_a_reason(self) -> None:
        with mock.patch.object(file_index_server.shutil, "which", return_value=None):
            result = self.call("kde", {"query": "report"})
        self.assertTrue(result["isError"])
        self.assertIn("baloosearch6", result["content"][0]["text"])


class ChoiceTests(unittest.TestCase):
    def web(self, searxng: str = "", programs: tuple[str, ...] = ("npx", "uvx")) -> list[dict[str, Any]]:
        with mock.patch.object(search_choices.mcp_discovery, "discover_servers", return_value=[]), \
                mock.patch.object(search_choices, "local_searxng", return_value=searxng), \
                mock.patch.object(search_choices.shutil, "which", side_effect=lambda name: name if name in programs else None):
            return search_choices.choices("web_search", default_settings())

    def test_with_nothing_found_the_keyless_web_search_is_recommended(self) -> None:
        listed = self.web()
        self.assertEqual([item["id"] for item in listed if item["recommended"]], ["suggested:duckduckgo"])
        self.assertEqual(listed[-1]["id"], "suggested:searxng")

    def test_a_local_searxng_is_filled_in_and_recommended(self) -> None:
        listed = self.web(searxng="http://127.0.0.1:8890")
        first = listed[0]
        self.assertEqual((first["id"], first["recommended"]), ("suggested:searxng", True))
        self.assertEqual(first["inputs"][0]["value"], "http://127.0.0.1:8890")

    def test_a_missing_program_is_explained_and_not_recommended(self) -> None:
        listed = self.web(programs=())
        self.assertFalse(any(item["recommended"] for item in listed))
        self.assertIn("Needs uv", next(item for item in listed if item["id"] == "suggested:duckduckgo")["problem"])

    def test_kde_index_that_is_off_says_choosing_it_switches_it_on(self) -> None:
        with mock.patch.object(search_choices.mcp_discovery, "discover_servers", return_value=[]), \
                mock.patch.object(search_choices, "kde_index_state", return_value="off"), \
                mock.patch.object(search_choices, "locate_covers_home", return_value=False):
            listed = search_choices.choices("file_search", default_settings())
        self.assertEqual([item["id"] for item in listed], ["builtin:kde"])
        self.assertTrue(listed[0]["recommended"])
        self.assertIn("switches it on", listed[0]["detail"])


class FakeDaemon:
    """Just what ``search_setup.use`` needs from ``AssistantServer``."""

    def __init__(self) -> None:
        self.settings = validate_settings(default_settings())
        self.mcp = object()
        self.saves = 0

    def replace_settings(self, new_settings: Any) -> dict[str, Any]:
        self.settings = validate_settings(new_settings)
        self.saves += 1
        return self.settings


class UseTests(unittest.TestCase):
    def use(self, test_result: Any, choice: str = "suggested:duckduckgo", inputs: dict[str, str] | None = None):
        daemon = FakeDaemon()
        offered = {"name": "search", "inputSchema": {"properties": {"query": {"type": "string"}}}}
        def fake_test(*_: Any) -> ToolResult:
            if isinstance(test_result, Exception):
                raise test_result
            return test_result
        with mock.patch.object(search_setup.shutil, "which", return_value="/usr/bin/uvx"), \
                mock.patch.object(search_setup, "_first_start", return_value=offered), \
                mock.patch.object(search_setup, "call_role", side_effect=fake_test):
            return daemon, search_setup.use(daemon, "web_search", choice, inputs or {})

    def test_a_working_choice_adds_the_server_and_the_job(self) -> None:
        daemon, result = self.use(ToolResult(text="results", structured=None, is_error=False))
        self.assertTrue(result["ok"], result)
        self.assertEqual(daemon.settings["roles"]["web_search"]["server"], "duckduckgo")
        self.assertEqual(daemon.settings["tool_servers"]["duckduckgo"]["args"], ["duckduckgo-mcp-server@0.7.0"])

    def test_a_failed_test_search_puts_the_settings_back(self) -> None:
        daemon, result = self.use(McpError("no network"))
        self.assertFalse(result["ok"])
        self.assertIn("nothing was changed", result["error"])
        self.assertEqual((daemon.settings["roles"], daemon.settings["tool_servers"]), ({}, {}))

    def test_a_required_key_must_be_filled_in(self) -> None:
        daemon, result = self.use(ToolResult(text="", structured=None, is_error=False), choice="suggested:brave")
        self.assertEqual(result, {"ok": False, "error": "Fill in Brave API key first."})
        self.assertEqual(daemon.saves, 0)


if __name__ == "__main__":
    unittest.main()
