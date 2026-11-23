"""End-to-end tests of the daemon's settings, tool and search endpoints.

A real ``AssistantServer`` runs on an ephemeral port with its settings file
and runtime directory in a temporary directory, and uses
``tests/fake_mcp_server.py`` as its tool server. Requests go over HTTP with
the server's token, so routing, validation, persistence and tool-server
supervision are covered together. ``/open`` is tested only for refusals so no
application is launched.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kde_ai_assistant.daemon_http import AssistantServer  # noqa: E402

FAKE_SERVER = str(Path(__file__).resolve().parent / "fake_mcp_server.py")
FAKE_ENTRY = {"command": sys.executable, "args": [FAKE_SERVER], "env": {"TOKEN": "abc"}}


class RouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.config_file = root / "config" / "config.json"
        self.server = AssistantServer("127.0.0.1", 0, root / "runtime", self.config_file, root / "history")
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.shutdown_tools()
        self._thread.join(timeout=5)
        self._tmp.cleanup()

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        request = Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}",
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.server.auth_token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def configure(self, with_role: bool = True, mode: str = "structured") -> None:
        settings = {"tool_servers": {"fake": dict(FAKE_ENTRY)}, "roles": {}}
        if with_role:
            settings["roles"]["file_search"] = {
                "server": "fake", "tool": "find_files", "arguments": {"limit": 3, "mode": mode}}
        status, reply = self.call("PUT", "/settings", {"settings": settings})
        self.assertEqual(status, 200, reply)

    def test_search_without_setup_says_so(self) -> None:
        status, reply = self.call("GET", "/search?q=tax")
        self.assertEqual((status, reply["code"]), (409, "not_configured"))
        self.assertFalse(self.call("GET", "/health")[1]["setup"]["file_search"])

    def test_search_returns_hits_and_respects_limit(self) -> None:
        self.configure()
        status, reply = self.call("GET", f"/search?q={quote('tax return')}&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual([hit["location"] for hit in reply["hits"]],
                         ["/tmp/fake/tax return-0.txt", "/tmp/fake/tax return-1.txt"])
        self.assertTrue(self.call("GET", "/health")[1]["setup"]["file_search"])
        self.assertEqual(self.call("GET", "/search?q=")[1]["hits"], [])
        self.assertEqual(self.call("GET", "/search?q=x&limit=many")[0], 400)

    def test_search_tool_failure_is_recoverable(self) -> None:
        self.configure(mode="error")
        status, reply = self.call("GET", "/search?q=tax")
        self.assertEqual((status, reply["code"]), (502, "tool_failed"))
        self.configure(mode="structured")
        self.assertEqual(self.call("GET", "/search?q=tax")[0], 200)

    def test_settings_are_saved_validated_and_never_leak_secrets(self) -> None:
        self.configure()
        self.assertEqual(json.loads(self.config_file.read_text())["tool_servers"]["fake"]["env"], {"TOKEN": "abc"})
        status, reply = self.call("GET", "/settings")
        self.assertEqual(reply["settings"]["tool_servers"]["fake"]["env"], {"TOKEN": None})
        self.assertNotIn("abc", json.dumps(reply))
        self.assertEqual(self.call("PUT", "/settings", {"settings": reply["settings"]})[0], 200)
        self.assertEqual(json.loads(self.config_file.read_text())["tool_servers"]["fake"]["env"], {"TOKEN": "abc"})
        status, reply = self.call("PUT", "/settings", {"settings": {"roles": {"file_search": {"server": "x", "tool": "y"}}}})
        self.assertEqual((status, reply["code"]), (400, "invalid"))
        self.assertIn("fake", json.loads(self.config_file.read_text())["tool_servers"])

    def test_settings_survive_a_restart_of_the_daemon(self) -> None:
        self.configure()
        other = AssistantServer("127.0.0.1", 0, Path(self._tmp.name) / "runtime2", self.config_file, Path(self._tmp.name) / "history")
        try:
            self.assertIn("file_search", other.settings["roles"])
            self.assertEqual(other.settings_error, "")
        finally:
            other.server_close()
            other.shutdown_tools()

    def test_unreadable_settings_are_reported_not_fatal(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text("{broken", encoding="utf-8")
        other = AssistantServer("127.0.0.1", 0, Path(self._tmp.name) / "runtime3", self.config_file, Path(self._tmp.name) / "history")
        try:
            self.assertIn("could not read", other.settings_error)
            self.assertEqual(other.settings["tool_servers"], {})
        finally:
            other.server_close()

    def test_tool_listing_includes_role_proposals_and_errors(self) -> None:
        self.configure(with_role=False)
        settings = self.call("GET", "/settings")[1]["settings"]
        settings["tool_servers"]["broken"] = {"command": "/nonexistent/server"}
        self.call("PUT", "/settings", {"settings": settings})
        servers = {item["name"]: item for item in self.call("GET", "/tools/servers")[1]["servers"]}
        self.assertEqual(len(servers["fake"]["tools"]), 5)
        self.assertEqual({(p["role"], p["config"]["tool"]) for p in servers["fake"]["proposals"]},
                         {("file_search", "find_files"), ("web_search", "web_lookup")})
        self.assertIn("could not start", servers["broken"]["error"])
        only = self.call("GET", "/tools/servers?name=fake")[1]["servers"]
        self.assertEqual([item["name"] for item in only], ["fake"])

    def test_removing_a_server_stops_its_process(self) -> None:
        self.configure()
        self.call("GET", "/search?q=tax")
        session = self.server.mcp.session("fake")
        self.call("PUT", "/settings", {"settings": {"tool_servers": {}, "roles": {}}})
        self.assertFalse(session.alive)

    def test_open_refuses_unsafe_or_missing_locations(self) -> None:
        for location in ("", "relative/file.txt", "ftp://example.org/x", "--help", "/nonexistent/file.txt"):
            with self.subTest(location=location):
                status, reply = self.call("POST", "/open", {"location": location})
                self.assertEqual((status, reply["ok"]), (400, False))

    def test_import_of_unknown_server_is_refused(self) -> None:
        status, reply = self.call("POST", "/tools/import", {"name": "definitely-not-configured-anywhere-xyz"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
