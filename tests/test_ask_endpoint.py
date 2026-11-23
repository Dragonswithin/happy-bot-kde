"""End-to-end tests of ``POST /ask`` and the model endpoints.

A real ``AssistantServer`` is pointed at ``tests/fake_model_service.py`` as
its model and ``tests/fake_mcp_server.py`` as its tool server. Requests go
over HTTP and the event stream is read from the socket, so the whole path is
covered: settings, registry assembly, the agent loop, tool execution through
MCP, event streaming, conversation memory and cancellation on disconnect.
Also covers model settings validation, secret redaction, the read-only
built-in tools and the conversation store.
"""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model_service import FakeModelService, chunks_for  # noqa: E402

from kde_ai_assistant import settings as settings_store  # noqa: E402
from kde_ai_assistant.conversations import MAX_CONVERSATIONS, ConversationStore  # noqa: E402
from kde_ai_assistant.daemon_http import AssistantServer  # noqa: E402
from kde_ai_assistant.settings import SettingsError, validate_settings  # noqa: E402
from kde_ai_assistant.tools import observe  # noqa: E402
from kde_ai_assistant.tools.registry import ToolFailure  # noqa: E402

FAKE_MCP = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


class AskEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.model = FakeModelService()
        self.server = AssistantServer("127.0.0.1", 0, root / "runtime", root / "config.json")
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.shutdown_tools()
        self._thread.join(timeout=5)
        self.model.close()
        self._tmp.cleanup()

    def request(self, method: str, path: str, body: dict | None = None) -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        connection.request(method, path, body=None if body is None else json.dumps(body), headers={
            "Authorization": f"Bearer {self.server.auth_token}", "Content-Type": "application/json"})
        self.addCleanup(connection.close)
        return connection.getresponse()

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        return json.loads(self.request(method, path, body).read())

    def ask(self, message: str, conversation_id: str = "") -> list[dict]:
        response = self.request("POST", "/ask", {"message": message, "conversation_id": conversation_id})
        return [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]

    def configure(self, read_only: bool = False) -> None:
        reply = self.call("PUT", "/settings", {"settings": {
            "tool_servers": {"fake": {"command": sys.executable, "args": [FAKE_MCP], "read_only": read_only}},
            "roles": {"file_search": {"server": "fake", "tool": "find_files", "arguments": {"limit": 2}}},
            "models": {"m": {"provider": "openai_compatible", "base_url": self.model.base_url,
                             "model": "fake-model", "api_key": "sk-secret"}},
            "active_model": "m",
        }})
        self.assertTrue(reply["ok"], reply)

    def test_turn_with_a_role_tool_streams_every_stage(self) -> None:
        self.configure()
        self.model.replies.append(chunks_for("Looking. ", [("c1", "fake__find_files", '{"query": "tax"}')]))
        self.model.replies.append(chunks_for("Found /tmp/fake/tax-0.txt"))
        events = self.ask("find my tax file")
        self.assertEqual([event["type"] for event in events],
                         ["start", "text_delta", "text_delta", "tool_call", "tool_result"]
                         + ["text_delta"] * 5 + ["done"])
        start = events[0]
        self.assertEqual(start["model"], "m")
        self.assertIn("fake__find_files", start["tools"])
        self.assertIn("current_time", start["tools"])
        result = next(event for event in events if event["type"] == "tool_result")
        self.assertTrue(result["ok"])
        second_request = self.model.requests[1]["messages"]
        self.assertEqual(second_request[-1]["role"], "tool")
        self.assertEqual(self.model.headers[0]["authorization"], "Bearer sk-secret")
        self.assertEqual(self.call("GET", "/health")["status"], "idle")

    def test_every_tool_is_offered_and_bridged_risk_follows_what_the_user_declared(self) -> None:
        self.configure(read_only=False)
        self.model.replies.append(chunks_for("ok"))
        offered = self.ask("hi")[0]["tools"]
        for name in ("fake__find_files", "fake__crash", "run_command", "trash_path", "arrange_window", "set_volume"):
            self.assertIn(name, offered)
        preferred = [t for t in self.model.requests[0]["tools"] if t["function"]["name"] == "fake__find_files"][0]
        self.assertTrue(preferred["function"]["description"].startswith("Preferred tool for finding"))

        from kde_ai_assistant.tools.catalog import build_registry
        registry, _ = build_registry(self.server.mcp, self.server.settings)
        self.assertEqual(registry.assess("fake__find_files", {})[0], "read")     # role-assigned
        self.assertEqual(registry.assess("fake__crash", {})[0], "change")        # unvouched server tool
        self.configure(read_only=True)
        registry, _ = build_registry(self.server.mcp, self.server.settings)
        self.assertEqual(registry.assess("fake__crash", {})[0], "read")

    def test_conversation_is_remembered_and_new_ones_start_clean(self) -> None:
        self.configure()
        self.model.replies += [chunks_for("My name is Bot."), chunks_for("You asked my name."), chunks_for("New.")]
        conversation_id = self.ask("what is your name")[0]["conversation_id"]
        follow_up = self.ask("what did I ask", conversation_id)
        self.assertEqual(follow_up[0]["conversation_id"], conversation_id)
        roles = [message["role"] for message in self.model.requests[1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertNotEqual(self.ask("hello")[0]["conversation_id"], conversation_id)
        self.assertEqual(len(self.model.requests[2]["messages"]), 2)

    def test_errors_are_events_not_broken_streams(self) -> None:
        self.assertEqual(self.ask("hi")[0]["code"], "not_configured")
        self.configure()
        self.assertEqual(self.ask("   ")[0]["code"], "invalid")
        self.model.replies.append((401, {"error": {"message": "bad key"}}))
        events = self.ask("hi")
        self.assertEqual([event["type"] for event in events], ["start", "error"])
        self.assertIn("rejected the API key", events[1]["message"])
        self.model.replies.append(chunks_for("recovered"))
        self.assertEqual(self.ask("again", events[0]["conversation_id"])[-1], {"type": "done", "stop": "answered"})

    def test_broken_tool_server_is_a_warning_and_the_turn_still_runs(self) -> None:
        self.configure()
        settings = self.call("GET", "/settings")["settings"]
        settings["tool_servers"]["dead"] = {"command": "/nonexistent/server", "read_only": True}
        self.call("PUT", "/settings", {"settings": settings})
        self.model.replies.append(chunks_for("still here"))
        events = self.ask("hi")
        self.assertIn("could not start tool server 'dead'", events[0]["warnings"][0])
        self.assertEqual(events[-1]["stop"], "answered")

    def test_client_disconnect_cancels_the_turn(self) -> None:
        self.configure(read_only=True)
        self.model.replies.append(chunks_for(tool_calls=[("c1", "fake__sleep", '{"seconds": 1.0}'),
                                                           ("c2", "fake__echo_env", '{"name": "X"}')]))
        self.model.replies.append(chunks_for("should never be requested"))
        response = self.request("POST", "/ask", {"message": "wait"})
        response.fp.readline()
        response.close()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self.call("GET", "/health")["status"] != "idle":
            time.sleep(0.1)
        self.assertEqual(self.call("GET", "/health")["status"], "idle")
        self.assertEqual(len(self.model.requests), 1)

    def test_cancel_endpoint_and_model_endpoints(self) -> None:
        self.assertFalse(self.call("POST", "/cancel", {"conversation_id": "nope"})["cancelled"])
        self.configure()
        self.model.replies.append(chunks_for("x"))
        conversation_id = self.ask("hi")[0]["conversation_id"]
        self.assertTrue(self.call("POST", "/cancel", {"conversation_id": conversation_id})["cancelled"])

        bare = self.model.base_url.removesuffix("/v1")
        probe = self.call("POST", "/models/probe", {"base_url": bare})
        self.assertEqual((probe["base_url"], probe["models"][0]["context_window"]), (self.model.base_url, 4096))
        self.assertEqual(self.call("POST", "/models/probe", {"base_url": "ftp://x"})["code"], "invalid")
        self.assertEqual(self.call("POST", "/models/probe", {"base_url": "http://127.0.0.1:9"})["code"], "unreachable")

        self.model.replies.append(chunks_for(tool_calls=[("t", "confirm_ready", "{}")]))
        self.assertEqual(self.call("POST", "/models/test", {})["tools"], True)
        self.model.replies.append(chunks_for("I cannot use tools"))
        self.assertEqual(self.call("POST", "/models/test", {"name": "m"})["tools"], False)
        self.assertEqual(self.call("POST", "/models/test", {"name": "ghost"})["code"], "invalid")

    def test_api_key_is_never_returned_and_survives_a_round_trip(self) -> None:
        self.configure()
        view = self.call("GET", "/settings")
        self.assertNotIn("sk-secret", json.dumps(view))
        self.assertIsNone(view["settings"]["models"]["m"]["api_key"])
        self.assertTrue(self.call("GET", "/health")["setup"]["model"])
        self.call("PUT", "/settings", {"settings": view["settings"]})
        self.assertEqual(self.server.settings["models"]["m"]["api_key"], "sk-secret")


class ModelSettingsTests(unittest.TestCase):
    def test_model_validation_messages(self) -> None:
        good = {"provider": "openai_compatible", "base_url": "http://h/v1/", "model": " m "}
        stored = validate_settings({"models": {"a": good}, "active_model": "a"})["models"]["a"]
        self.assertEqual((stored["base_url"], stored["model"], stored["context_window"]), ("http://h/v1", "m", 32768))
        cases = {
            "'provider' must be one of": {**good, "provider": "magic"},
            "'base_url' must start with": {**good, "base_url": "h/v1"},
            "'model' is required": {**good, "model": ""},
            "'context_window' must be": {**good, "context_window": 10},
            "unknown setting 'temperature'": {**good, "temperature": 1},
        }
        for message, model in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(SettingsError, message):
                validate_settings({"models": {"a": model}})
        with self.assertRaisesRegex(SettingsError, "model 'b' is not set up"):
            validate_settings({"models": {"a": good}, "active_model": "b"})
        self.assertIsNone(settings_store.active_model(validate_settings({"models": {"a": good}})))


class ObserveToolTests(unittest.TestCase):
    def test_file_tools_read_list_and_refuse_sensibly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.txt").write_text("hello world\n" * 3, encoding="utf-8")
            (root / "blob.bin").write_bytes(b"\x00\x01\x02" * 100)
            (root / "sub").mkdir()
            (root / "sub" / "big.dat").write_bytes(b"x" * 200_000)
            listing = observe.list_directory({"path": tmp})
            self.assertIn("notes.txt", listing)
            self.assertRegex(listing, r"dir .* sub")
            self.assertEqual(observe.read_text_file({"path": str(root / "notes.txt")}), "hello world\n" * 3)
            cut = observe.read_text_file({"path": str(root / "sub" / "big.dat"), "max_chars": 100})
            self.assertIn("file continues", cut)
            with self.assertRaisesRegex(ToolFailure, "binary file"):
                observe.read_text_file({"path": str(root / "blob.bin")})
            with self.assertRaisesRegex(ToolFailure, "cannot read"):
                observe.read_text_file({"path": str(root / "missing.txt")})
            with self.assertRaisesRegex(ToolFailure, "'path' is required"):
                observe.list_directory({})
            with self.assertRaisesRegex(ToolFailure, "must be a number"):
                observe.list_directory({"path": tmp, "limit": "ten"})
            usage = observe.disk_usage({"path": tmp})
            lines = usage.splitlines()
            self.assertTrue(lines[0].endswith("(whole folder)"), lines)
            self.assertTrue(lines[1].endswith("/sub"), lines)
            with self.assertRaisesRegex(ToolFailure, "not a folder"):
                observe.disk_usage({"path": str(root / "notes.txt")})

    def test_time_and_system_info_have_content(self) -> None:
        self.assertRegex(observe.current_time({}), r"\d{4}, \d\d:\d\d:\d\d")
        info = observe.system_info({})
        self.assertIn("cpu cores:", info)
        self.assertIn("memory:", info)

    def test_tool_definitions_are_all_read_risk_with_object_schemas(self) -> None:
        tools = observe.observe_tools()
        self.assertEqual(len({tool.name for tool in tools}), len(tools))
        for tool in tools:
            self.assertEqual((tool.risk, tool.parameters["type"]), ("read", "object"), tool.name)


class ConversationStoreTests(unittest.TestCase):
    def test_unknown_ids_start_new_conversations_and_old_ones_are_forgotten(self) -> None:
        store = ConversationStore()
        first = store.get_or_create()
        self.assertIs(store.get_or_create(first.id), first)
        self.assertIsNot(store.get_or_create("unknown-id"), first)
        busy = store.get_or_create()
        busy.turn_lock.acquire()
        for _ in range(MAX_CONVERSATIONS + 5):
            store.get_or_create()
        self.assertIs(store.get_or_create(busy.id), busy)
        self.assertIsNot(store.get_or_create(first.id), first)
        self.assertTrue(store.cancel(busy.id))
        self.assertTrue(busy.cancel.is_set())


if __name__ == "__main__":
    unittest.main()
