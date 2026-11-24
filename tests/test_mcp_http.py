"""Tests for MCP over HTTP (``mcp_http``) against a small fake server in this process.

The fake answers ``initialize`` with a session id, ``tools/list`` as an event
stream and ``tools/call`` as plain JSON, and refuses requests without the
expected API key header, so the session id, both reply forms, headers and
the error for a missing key are all exercised through ``McpManager``.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import settings as settings_store  # noqa: E402
from happy_bot.mcp_client import McpError, McpManager  # noqa: E402

SEEN: list[dict] = []


class FakeHttpMcp(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def do_DELETE(self) -> None:  # noqa: N802
        SEEN.append({"method": "DELETE", "session": self.headers.get("Mcp-Session-Id")})
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != "Bearer secret":
            self.send_response(401)
            self.end_headers()
            return
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append({"method": message.get("method"), "session": self.headers.get("Mcp-Session-Id")})
        if "id" not in message:
            self.send_response(202)
            self.end_headers()
            return
        if message["method"] == "initialize":
            body, kind, extra = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {}}), "application/json", {"Mcp-Session-Id": "s-1"}
        elif message["method"] == "tools/list":
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [{"name": "lookup", "inputSchema": {"type": "object"}}]}}
            body, kind, extra = f"event: message\ndata: {json.dumps(reply)}\n\n", "text/event-stream", {}
        else:
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": "found it"}]}}
            body, kind, extra = json.dumps(reply), "application/json", {}
        self.send_response(200)
        self.send_header("Content-Type", kind)
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body.encode())


class HttpMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        SEEN.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHttpMcp)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"

    def manager(self, key: str) -> McpManager:
        settings = settings_store.validate_settings({"tool_servers": {"remote": {"url": self.url, "headers": {"Authorization": key}}}})
        manager = McpManager()
        manager.configure(settings_store.server_specs(settings))
        self.addCleanup(manager.close_all)
        return manager

    def test_session_id_event_stream_and_json_replies(self) -> None:
        manager = self.manager("Bearer secret")
        self.assertEqual([tool["name"] for tool in manager.list_tools("remote")], ["lookup"])
        self.assertEqual(manager.call_tool("remote", "lookup", {}, 5).text, "found it")
        manager.close_all()
        self.assertEqual(SEEN[0], {"method": "initialize", "session": None})
        self.assertTrue(all(item["session"] == "s-1" for item in SEEN[1:]))
        self.assertEqual(SEEN[-1]["method"], "DELETE")

    def test_a_wrong_key_is_explained(self) -> None:
        with self.assertRaisesRegex(McpError, "HTTP 401 .check its API key"):
            self.manager("Bearer wrong").list_tools("remote")

    def test_settings_need_exactly_one_way_to_reach_a_server_and_hide_headers(self) -> None:
        with self.assertRaisesRegex(settings_store.SettingsError, "but not both"):
            settings_store.validate_settings({"tool_servers": {"x": {"command": "a", "url": self.url}}})
        settings = settings_store.validate_settings({"tool_servers": {"x": {"url": self.url, "headers": {"Authorization": "k"}}}})
        view = settings_store.redacted(settings)
        self.assertEqual(view["tool_servers"]["x"]["headers"], {"Authorization": None})
        merged = settings_store.merge_redacted(view, settings)
        self.assertEqual(merged["tool_servers"]["x"]["headers"], {"Authorization": "k"})


if __name__ == "__main__":
    unittest.main()
