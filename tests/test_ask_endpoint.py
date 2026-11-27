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
import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model_service import FakeModelService, chunks_for  # noqa: E402

from happy_bot import settings as settings_store  # noqa: E402
from happy_bot.conversations import MAX_CONVERSATIONS, ConversationStore  # noqa: E402
from happy_bot.daemon_http import AssistantServer  # noqa: E402
from happy_bot.settings import SettingsError, validate_settings  # noqa: E402
from happy_bot.tools import observe  # noqa: E402
from happy_bot.tools.registry import ToolFailure  # noqa: E402

FAKE_MCP = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


def done_core(event: dict) -> dict:
    """A ``done`` event without its usage and model details, which vary by model."""
    return {key: event[key] for key in ("type", "stop", "actions") if key in event}

class AskEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.model = FakeModelService()
        self.server = AssistantServer("127.0.0.1", 0, root / "runtime", root / "config.json", root / "history")
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
        context = [event for event in events if event["type"] == "context_usage"]
        self.assertEqual([event["estimated"] for event in context], [True, False, True, False])
        self.assertGreater(context[2]["used"], context[0]["used"])
        self.assertIsNone(context[-1]["capacity"])
        self.assertLess(context[-1]["used"], events[-1]["usage"]["input_tokens"])
        saved = self.call("GET", "/conversation?id=" + events[0]["conversation_id"])
        self.assertEqual(saved["context_usage"], context[-1])
        preview = self.call("GET", "/context/usage?id=" + saved["id"])["context_usage"]
        self.assertTrue(preview["estimated"])
        self.assertIsNone(preview["capacity"])
        self.assertEqual([event["type"] for event in events if event["type"] != "context_usage"],
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
        self.assertEqual(self.model.headers[-1]["authorization"], "Bearer sk-secret")  # the chat requests, after the /slots check
        self.assertEqual(self.call("GET", "/health")["status"], "idle")

    def test_dry_run_offers_only_look_ups_and_ephemeral_requests_are_not_kept(self) -> None:
        self.configure()
        self.model.replies.append(chunks_for("plan"))
        response = self.request("POST", "/ask", {"message": "tidy my desktop", "dry_run": True, "ephemeral": True})
        events = [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]
        offered = events[0]["tools"]
        self.assertIn("list_directory", offered)
        self.assertNotIn("trash_path", offered)
        self.assertNotIn("run_command", offered)
        self.assertTrue(self.model.requests[0]["messages"][-1]["content"].startswith("Dry run:"))
        self.assertEqual(self.call("GET", "/conversations")["conversations"], [])
        self.model.replies.append(chunks_for("x"))
        response = self.request("POST", "/ask", {"message": "hi", "model": "ghost"})
        self.assertIn("no model named ghost", response.read().decode())

    def test_answer_buttons_are_offered_only_to_a_window_that_draws_them(self) -> None:
        self.configure()
        for buttons in (True, False):
            self.model.replies.append(chunks_for("ok"))
            response = self.request("POST", "/ask", {"message": "minecraft", "buttons": buttons, "ephemeral": True})
            events = [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]
            offered = set(events[0]["tools"])
            self.assertEqual({"ask_user", "suggest_next"} <= offered, buttons, offered & {"ask_user", "suggest_next"})

    def test_every_tool_is_offered_and_bridged_risk_follows_what_the_user_declared(self) -> None:
        self.configure(read_only=False)
        self.model.replies.append(chunks_for("ok"))
        offered = self.ask("hi")[0]["tools"]
        for name in ("fake__find_files", "fake__crash", "run_command", "trash_path", "arrange_window", "set_volume"):
            self.assertIn(name, offered)
        preferred = [t for t in self.model.requests[0]["tools"] if t["function"]["name"] == "fake__find_files"][0]
        self.assertTrue(preferred["function"]["description"].startswith("Preferred tool for finding"))

        from happy_bot.tools.catalog import build_registry
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

    def test_the_application_the_user_came_from_reaches_the_model_only(self) -> None:
        self.configure()
        self.model.replies.append(chunks_for("Use Ctrl+Shift+L."))
        about = {"app": "Kate", "class": "org.kde.kate", "title": "notes.txt — Kate"}
        response = self.request("POST", "/ask", {"message": "how do I split the view?", "about_window": about})
        events = [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]
        sent = self.model.requests[-1]["messages"][-1]["content"]
        self.assertTrue(sent.startswith("[Background from the user's computer, not part of the request: they had "
                                        "the application Kate"), sent)
        self.assertIn("If they name another application or ask about something else, answer that", sent)
        self.assertTrue(sent.endswith("how do I split the view?"))
        opened = self.call("GET", f"/conversation?id={events[0]['conversation_id']}")
        self.assertEqual(opened["events"][0]["text"], "how do I split the view?")  # the chat shows what was typed

    def test_with_app_awareness_off_no_ai_is_told_about_the_application(self) -> None:
        self.configure()
        settings = self.call("GET", "/settings")["settings"]
        settings["agent"]["app_context"] = "off"
        self.call("PUT", "/settings", {"settings": settings})
        self.assertEqual(self.call("GET", "/context/app")["app"], "")
        with mock.patch("happy_bot.app_context.preview_screenshot") as capture:
            preview = self.call("POST", "/context/screenshot", {"preview": True, "desktop": True})
            self.assertEqual(preview["reason"], "disabled")
            capture.assert_not_called()
        self.model.replies.append(chunks_for("Use Ctrl+Shift+L."))
        about = {"app": "Kate", "class": "org.kde.kate", "title": "notes.txt — Kate"}
        self.request("POST", "/ask", {"message": "how do I split the view?", "about_window": about}).read()
        self.assertEqual(self.model.requests[-1]["messages"][-1]["content"], "how do I split the view?")

    def test_help_attaches_the_preview_chosen_by_this_client(self) -> None:
        self.configure()
        folder = self.server.runtime_dir / "screenshots"
        folder.mkdir()
        pictures = [folder / (letter * 32 + ".png") for letter in "ab"]
        for picture in pictures:
            picture.write_bytes(b"\x89PNG" + picture.stem.encode())
        with mock.patch("happy_bot.app_snapshot.capture_window", side_effect=map(str, pictures)) as capture:
            first, second = [self.call("POST", "/context/screenshot", {"window": "{w}", "preview": True})
                             for _ in pictures]
        self.assertEqual(capture.call_args_list, [mock.call("{w}", folder)] * 2)
        self.assertEqual(first["models"], [])  # a text-only AI still gets a local preview
        self.assertEqual(first["url"], pictures[0].as_uri())
        self.assertNotEqual(first["id"], second["id"])
        self.assertFalse(self.model.requests)

        def ask_with(capture_id):
            self.model.replies.append(chunks_for("ok"))
            self.request("POST", "/ask", {"message": "what is this?", "full_context": True,
                                         "screenshot_id": capture_id}).read()
            return self.model.requests[-1]["messages"][-1]["content"]

        self.assertEqual(ask_with(first["id"]), "what is this?")
        settings = self.call("GET", "/settings")["settings"]
        settings["models"]["m"]["vision"] = True
        self.call("PUT", "/settings", {"settings": settings})
        from happy_bot.providers.base import image_data_url
        self.assertEqual(ask_with(first["id"])[1]["image_url"]["url"], image_data_url(str(pictures[0])))
        self.assertEqual(ask_with(str(pictures[0])), "what is this?")
        settings["agent"]["app_context"] = "off"
        self.call("PUT", "/settings", {"settings": settings})
        self.assertEqual(ask_with(first["id"]), "what is this?")

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow enables Help screenshot edits")
    def test_edit_preview_then_send_or_omit_it_for_one_turn(self) -> None:
        from PIL import Image
        from happy_bot.providers.base import image_data_url

        self.configure()
        settings = self.call("GET", "/settings")["settings"]
        settings["models"]["m"]["vision"] = True
        self.call("PUT", "/settings", {"settings": settings})
        folder = self.server.runtime_dir / "screenshots"
        folder.mkdir()
        original = folder / ("c" * 32 + ".png")
        with Image.new("RGB", (200, 100), "green") as sample:
            sample.save(original)

        def edit(ident, action, coords):
            return self.call("POST", "/context/screenshot/edit", {"id": ident, "action": action, "coordinates": coords})

        self.assertFalse(edit("../x", "read", [])["ok"])
        self.assertFalse(edit(original.stem, "crop", [0, 0, 3, 1])["ok"])
        marked = edit(original.stem, "point", [0.5, 0.5])["id"]
        crop = edit(marked, "crop", [0.25, 0, 0.75, 1])["id"]
        path = folder / (crop + ".png")
        with Image.open(path) as image:
            self.assertEqual(image.size, (100, 100))
            self.assertIn((209, 44, 66), [color for _, color in image.getcolors()])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with mock.patch("happy_bot.help_screenshot.text_from_image", return_value="File menu\n\nError 42\nAccess denied") as read:
            self.assertEqual(edit(crop, "read", [])["text"], "Error 42\nAccess denied")
            read.assert_called_once_with({"path": str(path)})

        def turn(conversation_id="", **options):
            self.model.replies.append(chunks_for("ok"))
            response = self.request("POST", "/ask", {"message": "help", "conversation_id": conversation_id,
                                    "full_context": True, **options})
            events = [json.loads(line[5:]) for line in response.read().decode().splitlines() if line.startswith("data:")]
            return events[0]["conversation_id"], self.model.requests[-1]["messages"]

        cid, _ = turn(screenshot_id=original.stem)  # legacy saved chat contains an earlier image
        _, sent = turn(cid, screenshot_id=crop, include_screenshot=True, walkthrough=True)
        self.assertIn("one action", sent[0]["content"])
        self.assertIsInstance(sent[1]["content"], str)
        self.assertEqual(sent[-1]["content"][1]["image_url"]["url"], image_data_url(str(path)))
        _, sent = turn(cid, screenshot_id=crop, include_screenshot=False, help_error_text="Error 42")
        self.assertTrue(all(isinstance(msg["content"], str) for msg in sent))
        self.assertIn("Error 42", sent[-1]["content"])
        self.assertNotIn("user chose a walkthrough", sent[0]["content"])

        settings["agent"]["app_context"] = "off"
        self.call("PUT", "/settings", {"settings": settings})
        self.assertFalse(edit(crop, "read", [])["ok"])
        _, sent = turn(cid, screenshot_id=crop, include_screenshot=True, help_error_text="Secret from app")
        self.assertEqual(sent[-1]["content"], "help")

    def test_errors_are_events_not_broken_streams(self) -> None:
        self.assertEqual(self.ask("hi")[0]["code"], "not_configured")
        self.configure()
        self.assertEqual(self.ask("   ")[0]["code"], "invalid")
        self.model.replies.append((401, {"error": {"message": "bad key"}}))
        events = self.ask("hi")
        self.assertEqual([event["type"] for event in events], ["start", "context_usage", "error"])
        self.assertIn("rejected the API key", events[-1]["message"])
        self.model.replies.append(chunks_for("recovered"))
        self.assertEqual(done_core(self.ask("again", events[0]["conversation_id"])[-1]), {"type": "done", "stop": "answered", "actions": []})

    def test_live_questions_and_scheduled_turns_each_have_one_cue(self) -> None:
        with mock.patch("happy_bot.sounds.play") as play:
            self.ask("before setup")
            self.assertEqual([call.args[1] for call in play.call_args_list], ["error"])
            self.configure()
            play.reset_mock()
            self.model.replies.append(chunks_for(tool_calls=[
                ("question", "ask_user", '{"question":"Which one?","choices":["One","Two"]}')]))
            with self.request("POST", "/ask", {"message": "choose", "buttons": True, "background": True}) as response:
                response.read()
            self.assertEqual([call.args[1] for call in play.call_args_list], ["attention"])
            play.reset_mock()
            self.model.replies.append(chunks_for("Done"))
            with self.request("POST", "/ask", {"message": "routine", "background": True}) as response:
                response.read()
            self.assertEqual([call.args[1] for call in play.call_args_list], ["background"])

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
        health = self.call("GET", "/health")
        self.assertTrue(health["setup"]["model"])
        self.assertEqual(health["models"], [{"name": "m", "online": False, "context_window": 0}])  # for the popup's picker; no secrets
        self.call("PUT", "/settings", {"settings": view["settings"]})
        self.assertEqual(self.server.settings["models"]["m"]["api_key"], "sk-secret")


class ModelSettingsTests(unittest.TestCase):
    def test_model_validation_messages(self) -> None:
        good = {"provider": "openai_compatible", "base_url": "http://h/v1/", "model": " m "}
        stored = validate_settings({"models": {"a": good}, "active_model": "a"})["models"]["a"]
        self.assertEqual((stored["base_url"], stored["model"], stored["context_window"]), ("http://h/v1", "m", 0))
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
        # Every model set up is in the order, so a lone model answers without being chosen.
        self.assertEqual(settings_store.active_model(validate_settings({"models": {"a": good}}))["model"], "m")
        self.assertIsNone(settings_store.active_model(validate_settings({})))


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


class ConversationHistoryTests(unittest.TestCase):
    """Saving, reopening, continuing, listing, deleting and pruning conversations."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.model = FakeModelService()
        self.server = self.start_server()

    def start_server(self) -> AssistantServer:
        server = AssistantServer("127.0.0.1", 0, self.root / "runtime", self.root / "config.json", self.root / "history")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def tearDown(self) -> None:
        self.model.close()
        self._tmp.cleanup()

    def call(self, server, method: str, path: str, body: dict | None = None) -> dict:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=20)
        connection.request(method, path, body=None if body is None else json.dumps(body), headers={
            "Authorization": f"Bearer {server.auth_token}", "Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read().decode()
        connection.close()
        if path == "/ask":
            return [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:")]
        return json.loads(raw)

    def configure(self, server, days: int = 30) -> None:
        reply = self.call(server, "PUT", "/settings", {"settings": {
            "models": {"m": {"provider": "openai_compatible", "base_url": self.model.base_url, "model": "fake-model"}},
            "active_model": "m", "history_days": days}})
        self.assertTrue(reply["ok"], reply)

    def test_conversation_is_saved_privately_and_reopens_after_a_restart(self) -> None:
        import stat

        self.configure(self.server)
        self.model.replies += [chunks_for("It is sunny."), chunks_for("Still sunny.")]
        first = self.call(self.server, "POST", "/ask", {"message": "what is the weather like today", "model": "m"})
        conversation_id = first[0]["conversation_id"]
        saved = self.root / "history" / f"{conversation_id}.json"
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(saved.parent.stat().st_mode), 0o700)

        self.server.shutdown()
        restarted = self.start_server()
        listed = self.call(restarted, "GET", "/conversations")["conversations"]
        self.assertEqual([(item["id"], item["title"], item["requests"]) for item in listed],
                         [(conversation_id, "what is the weather like today", 1)])
        opened = self.call(restarted, "GET", f"/conversation?id={conversation_id}")
        self.assertEqual(opened["created"], first[0]["created"])
        self.assertEqual(opened["model"], "m")  # the AI picked for this chat comes back with it
        self.assertEqual([event["type"] for event in opened["events"]], ["user", "text_delta", "done"])
        self.assertEqual(opened["events"][1]["text"], "It is sunny.")

        follow_up = self.call(restarted, "POST", "/ask", {"message": "and tomorrow?", "conversation_id": conversation_id})
        self.assertEqual(follow_up[0]["conversation_id"], conversation_id)
        sent = [message["role"] for message in self.model.requests[-1]["messages"]]
        self.assertEqual(sent, ["system", "user", "assistant", "user"])
        self.assertEqual(self.call(restarted, "GET", "/conversations")["conversations"][0]["requests"], 2)

    def test_new_conversations_keep_the_old_ones_and_delete_works(self) -> None:
        self.configure(self.server)
        self.model.replies += [chunks_for("one"), chunks_for("two"), chunks_for("three")]
        ids = [self.call(self.server, "POST", "/ask", {"message": text})[0]["conversation_id"] for text in ("a1", "b2", "c3")]
        listed = [item["id"] for item in self.call(self.server, "GET", "/conversations")["conversations"]]
        self.assertEqual(listed, list(reversed(ids)))
        self.assertTrue(self.call(self.server, "POST", "/conversations/delete", {"id": ids[0]})["ok"])
        self.assertFalse(self.call(self.server, "POST", "/conversations/delete", {"id": ids[0]})["ok"])
        self.assertFalse(self.call(self.server, "GET", f"/conversation?id={ids[0]}")["ok"])
        self.assertEqual(self.call(self.server, "POST", "/conversations/delete", {"all": True})["deleted"], 2)
        self.assertEqual(self.call(self.server, "GET", "/conversations")["conversations"], [])

    def test_old_conversations_are_pruned_and_zero_days_keeps_nothing(self) -> None:
        import os
        import time as time_module

        self.configure(self.server, days=30)
        self.model.replies += [chunks_for("x"), chunks_for("y")]
        old = self.call(self.server, "POST", "/ask", {"message": "old one"})[0]["conversation_id"]
        record_path = self.root / "history" / f"{old}.json"
        record = json.loads(record_path.read_text())
        record["updated"] = time_module.time() - 31 * 86400
        record_path.write_text(json.dumps(record))
        self.call(self.server, "POST", "/ask", {"message": "new one"})
        self.assertFalse(record_path.exists())
        self.configure(self.server, days=0)
        self.assertEqual(os.listdir(self.root / "history"), [])
        self.model.replies.append(chunks_for("z"))
        self.call(self.server, "POST", "/ask", {"message": "not saved"})
        self.assertEqual(os.listdir(self.root / "history"), [])

    def test_ids_cannot_escape_the_history_folder(self) -> None:
        from happy_bot.conversation_archive import ConversationArchive

        archive = ConversationArchive(self.root / "history", days=30)
        for bad in ("../config", "a/b", "", "x" * 100, "../../etc/passwd"):
            with self.subTest(bad=bad):
                self.assertIsNone(archive.load(bad))
                self.assertFalse(archive.delete(bad))
        archive.save({"id": "../escape", "events": []})
        self.assertFalse((self.root / "escape.json").exists())

    def test_text_pieces_are_joined_and_liveness_events_dropped(self) -> None:
        from happy_bot.conversations import Conversation

        conversation = Conversation(id="abcd")
        for event in ({"type": "start"}, {"type": "thinking"}, {"type": "text_delta", "text": "Hel"},
                      {"type": "text_delta", "text": "lo"}, {"type": "tool_call", "id": "1", "name": "t"},
                      {"type": "text_delta", "text": "!"}):
            conversation.record(event)
        self.assertEqual(conversation.events, [
            {"type": "text_delta", "text": "Hello"}, {"type": "tool_call", "id": "1", "name": "t"},
            {"type": "text_delta", "text": "!"}])

    def test_history_days_is_validated(self) -> None:
        self.assertEqual(validate_settings({})["history_days"], 30)
        for bad in (-1, 4000, "30", True):
            with self.subTest(bad=bad), self.assertRaisesRegex(SettingsError, "history_days"):
                validate_settings({"history_days": bad})
