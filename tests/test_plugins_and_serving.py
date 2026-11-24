"""Tests for user plugins and for lending the built-in tools to other AI programs.

Plugins are written into a temporary plugins folder and loaded for real. The
lending endpoints run on a real ``AssistantServer``; ``mcp_serve.handle`` is
driven with a stub of the CLI's ``request_json`` so the MCP messages it
produces can be checked without a second process.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant import daemon_routes, mcp_serve  # noqa: E402
from kde_ai_assistant.daemon_http import AssistantServer  # noqa: E402
from kde_ai_assistant.mcp_client import McpManager  # noqa: E402
from kde_ai_assistant.settings import validate_settings  # noqa: E402
from kde_ai_assistant.tools import catalog, plugins  # noqa: E402

GOOD = '''from kde_ai_assistant.tools.registry import RISK_READ, Tool, object_schema

def tools():
    return [Tool("say_hello", "Greets.", object_schema({"name": {"type": "string"}}, ["name"]), RISK_READ,
                 lambda arguments: "Hello, " + arguments["name"] + "!")]
'''


class PluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def test_good_plugins_load_and_broken_or_unsafe_ones_are_reported(self) -> None:
        (self.folder / "hello.py").write_text(GOOD)
        (self.folder / "broken.py").write_text("def tools(:\n")
        (self.folder / "loose.py").write_text(GOOD)
        os.chmod(self.folder / "loose.py", 0o666)
        tools, warnings = plugins.load_plugins(self.folder)
        self.assertEqual([tool.name for tool in tools], ["say_hello"])
        self.assertEqual(tools[0].handler({"name": "Ada"}), "Hello, Ada!")
        self.assertEqual(tools[0].source, "plugin:hello")
        self.assertTrue(any("broken.py failed to load" in warning for warning in warnings))
        self.assertTrue(any("loose.py was not loaded" in warning for warning in warnings))

    def test_plugins_are_offered_only_when_switched_on(self) -> None:
        (self.folder / "hello.py").write_text(GOOD)
        with mock.patch.object(plugins, "plugin_dir", return_value=self.folder):
            off = catalog.build_registry(McpManager(), validate_settings({}))[0].names()
            on = catalog.build_registry(McpManager(), validate_settings({"agent": {"load_plugins": True}}))[0].names()
        self.assertNotIn("say_hello", off)
        self.assertIn("say_hello", on)


class ServingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.server = AssistantServer("127.0.0.1", 0, root / "runtime", root / "config.json", root / "history")
        self.addCleanup(self.server.server_close)

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        return daemon_routes.ROUTES[(method, path)](self.server, {}, body or {})

    def test_lending_is_off_until_switched_on_and_approval_calls_are_refused(self) -> None:
        self.assertEqual(self.call("GET", "/tools/catalog")[0], 403)
        self.server.replace_settings(validate_settings({"agent": {"serve_tools": True}}))
        names = [tool["name"] for tool in self.call("GET", "/tools/catalog")[1]["tools"]]
        self.assertIn("current_time", names)
        status, reply = self.call("POST", "/tools/run", {"name": "current_time", "arguments": {}})
        self.assertTrue(reply["succeeded"])
        with tempfile.NamedTemporaryFile() as victim:
            reply = self.call("POST", "/tools/run", {"name": "trash_path", "arguments": {"path": victim.name}})[1]
            self.assertFalse(reply["succeeded"])
            self.assertIn("needs the user's approval", reply["text"])
            self.assertTrue(Path(victim.name).exists())
        log = (self.server.runtime_dir / "actions.jsonl").read_text()
        self.assertIn("refused for another program", log)

    def test_mcp_messages(self) -> None:
        def request_json(method, path, body=None, timeout=10.0):
            if path == "/tools/catalog":
                return {"ok": True, "tools": [{"name": "t", "description": "", "inputSchema": {"type": "object"}}]}
            return {"ok": True, "succeeded": False, "text": "Refused"}

        stdin = io.StringIO("\n".join(json.dumps(message) for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "t", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})) + "\nnot json\n")
        stdout = io.StringIO()
        mcp_serve.serve(request_json, stdin, stdout)
        replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([reply.get("id") for reply in replies], [1, 2, 3, 4, None])
        self.assertEqual(replies[1]["result"]["tools"][0]["name"], "t")
        self.assertEqual(replies[2]["result"], {"content": [{"type": "text", "text": "Refused"}], "isError": True})
        self.assertEqual(replies[3]["error"]["code"], -32601)
        self.assertEqual(replies[4]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
