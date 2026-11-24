"""Tests for the stdio MCP client and supervisor against a real child process.

Every test launches ``tests/fake_mcp_server.py`` through ``McpManager`` and
talks to it over pipes, so the handshake, paging, concurrent calls, timeouts,
crash recovery and shutdown are exercised end to end. No network, no user
configuration.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant import mcp_client  # noqa: E402
from kde_ai_assistant.mcp_client import McpError, McpManager, McpServerSpec  # noqa: E402

FAKE_SERVER = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


def fake_spec(name: str = "fake", env: tuple[tuple[str, str], ...] = ()) -> McpServerSpec:
    return McpServerSpec(name=name, command=sys.executable, args=(FAKE_SERVER,), env=env)


class McpManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = McpManager()
        self.manager.configure([fake_spec()])
        self.addCleanup(self.manager.close_all)

    def test_lists_all_pages_of_tools(self) -> None:
        names = [tool["name"] for tool in self.manager.list_tools("fake")]
        self.assertEqual(names, ["find_files", "web_lookup", "echo_env", "sleep", "crash"])

    def test_server_is_started_lazily(self) -> None:
        self.assertEqual(self.manager.status(), {"fake": "stopped"})
        self.manager.list_tools("fake")
        self.assertEqual(self.manager.status(), {"fake": "running"})

    def test_call_returns_text_and_structured_content(self) -> None:
        result = self.manager.call_tool("fake", "find_files", {"query": "tax", "limit": 2}, 10)
        self.assertFalse(result.is_error)
        self.assertEqual(len(result.structured["hits"]), 2)
        self.assertEqual(result.text, "see structured")

    def test_tool_error_flag_is_reported(self) -> None:
        result = self.manager.call_tool("fake", "find_files", {"query": "x", "mode": "error"}, 10)
        self.assertTrue(result.is_error)
        self.assertEqual(result.text, "index is offline")

    def test_protocol_error_raises(self) -> None:
        with self.assertRaisesRegex(McpError, "unknown tool"):
            self.manager.call_tool("fake", "no_such_tool", {}, 10)

    def test_configured_environment_reaches_the_server(self) -> None:
        self.manager.configure([fake_spec(env=(("FAKE_SECRET", "s3cret"),))])
        self.assertEqual(self.manager.call_tool("fake", "echo_env", {"name": "FAKE_SECRET"}, 10).text, "s3cret")

    def test_timeout_raises_and_session_stays_usable(self) -> None:
        with self.assertRaisesRegex(McpError, "did not answer"):
            self.manager.call_tool("fake", "sleep", {"seconds": 1.5}, 0.2)
        self.assertEqual(self.manager.call_tool("fake", "echo_env", {"name": "NOPE"}, 10).text, "")

    def test_concurrent_calls_get_their_own_replies(self) -> None:
        results: dict[int, str] = {}

        def worker(index: int) -> None:
            reply = self.manager.call_tool("fake", "find_files", {"query": f"q{index}", "limit": 1}, 10)
            results[index] = reply.structured["query"]

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(results, {index: f"q{index}" for index in range(8)})

    def test_crash_reports_stderr_then_recovers_after_the_restart_interval(self) -> None:
        with self.assertRaisesRegex(McpError, "stopped unexpectedly.*simulated crash"):
            self.manager.call_tool("fake", "crash", {}, 10)
        with self.assertRaisesRegex(McpError, "retrying shortly"):
            self.manager.list_tools("fake")
        with mock.patch.object(mcp_client, "RESTART_INTERVAL_SECONDS", 0.0):
            self.assertEqual(len(self.manager.list_tools("fake")), 5)

    def test_unknown_server_and_bad_command(self) -> None:
        with self.assertRaisesRegex(McpError, "not set up"):
            self.manager.list_tools("missing")
        self.manager.configure([McpServerSpec(name="broken", command="/nonexistent/tool-server")])
        with self.assertRaisesRegex(McpError, "could not start"):
            self.manager.list_tools("broken")

    def test_server_that_never_initialises_fails_cleanly(self) -> None:
        silent = McpServerSpec(name="silent", command=sys.executable, args=("-c", "import time; time.sleep(30)"))
        with self.assertRaisesRegex(McpError, "did not answer"):
            mcp_client.McpSession(silent, startup_timeout=0.3)

    def test_reconfigure_stops_removed_servers_and_close_all_stops_the_rest(self) -> None:
        session = self.manager.session("fake")
        self.manager.configure([])
        self.assertFalse(session.alive)
        self.manager.configure([fake_spec("again")])
        second = self.manager.session("again")
        self.manager.close_all()
        self.assertFalse(second.alive)
        self.assertEqual(self.manager.status(), {"again": "stopped"})


if __name__ == "__main__":
    unittest.main()
