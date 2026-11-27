"""Tests for the OpenAI-compatible provider, the agent loop and history trimming.

Provider tests talk real HTTP to ``tests/fake_model_service.py``, so request
encoding, stream parsing, tool-call reassembly and error mapping are checked
against the wire format. Agent-loop tests use a scripted in-memory provider
and plain Python tools, so they check only the loop's own rules: event order,
history validity, step limit, cancellation and failure handling.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_model_service import FakeModelService, chunks_for  # noqa: E402

from happy_bot.agent_loop import run_turn  # noqa: E402
from happy_bot.conversation import (  # noqa: E402
    Message, TextDelta, ThinkingDelta, ToolCall, ToolCallReady, ToolSpec, TurnEnd, trim_history)
from happy_bot.providers import ProviderError, create_provider  # noqa: E402
from happy_bot.providers.openai_compatible import OpenAICompatibleProvider, list_models  # noqa: E402
from happy_bot.tools.registry import RISK_DANGER, RISK_READ, Tool, ToolFailure, ToolRegistry, object_schema  # noqa: E402

ECHO = ToolSpec("echo", "Echo text.", object_schema({"text": {"type": "string"}}, ["text"]))


def done_core(event: dict) -> dict:
    """A ``done`` event without its usage and model details, which vary by model."""
    return {key: event[key] for key in ("type", "stop", "actions") if key in event}

class ContextEstimateTests(unittest.TestCase):
    def test_counts_only_prepared_input_and_flags_uncounted_images(self) -> None:
        from happy_bot.context_meter import estimate

        base = [Message("system", "User instructions"), Message("user", "Explain this")]
        with_image = [base[0], Message("user", base[1].text, images=("capture.png",))]
        with_result = [*with_image, Message("tool", "Tool readings " * 100)]
        plain = estimate(base, [], 4096)
        illustrated = estimate(with_image, [], 4096)
        result = estimate(with_result, [ECHO], 0)
        self.assertEqual(plain["used"], illustrated["used"])
        self.assertEqual(illustrated["image_count"], 1)
        self.assertGreater(result["used"], illustrated["used"])
        self.assertIsNone(result["capacity"])


class ProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FakeModelService()
        self.addCleanup(self.service.close)
        self.provider = OpenAICompatibleProvider(self.service.base_url, "fake-model", api_key="sk-test", timeout=5)

    def run_stream(self, messages=None, tools=(), cancel=None):
        return list(self.provider.stream(messages or [Message("user", "hi")], list(tools), cancel or threading.Event()))

    def test_text_reply_streams_in_order_with_usage(self) -> None:
        self.service.replies.append(chunks_for("Hello there, friend", reasoning=True))
        events = self.run_stream()
        self.assertIsInstance(events[0], ThinkingDelta)
        self.assertEqual("".join(e.text for e in events if isinstance(e, TextDelta)), "Hello there, friend")
        end = events[-1]
        self.assertEqual((end.stop_reason, end.input_tokens, end.output_tokens), ("stop", 11, 7))
        self.assertIn('"reasoning_content": "thinking..."', end.echo)

    def test_echo_goes_back_only_to_the_service_that_wrote_it(self) -> None:
        self.service.replies.append(chunks_for("first", reasoning=True))
        echo = self.run_stream()[-1].echo
        call = ToolCall("c1", "echo", {}, echo=echo.replace("reasoning_content", "extra_content"))
        assistant = Message("assistant", "", (call,), echo=echo)
        self.service.replies.append(chunks_for("again"))
        self.run_stream([Message("user", "hi"), assistant, Message("tool", "done", tool_call_id="c1")])
        sent = self.service.requests[-1]["messages"][1]
        self.assertEqual(sent["reasoning_content"], "thinking...")
        self.assertEqual(sent["tool_calls"][0]["extra_content"], "thinking...")
        other = OpenAICompatibleProvider("http://127.0.0.1:1/v1", "m")
        from happy_bot.providers.openai_compatible import _message_to_wire
        self.assertNotIn("reasoning_content", _message_to_wire(assistant, other.base_url))
        from happy_bot.conversation_archive import message_from_json, message_to_json
        self.assertEqual(message_from_json(message_to_json(assistant)), assistant)

    def test_request_carries_model_key_tools_and_full_conversation(self) -> None:
        self.service.replies.append(chunks_for("ok"))
        call = ToolCall("c1", "echo", {"text": "héllo"})
        self.run_stream([
            Message("system", "be brief"), Message("user", "say it"),
            Message("assistant", "", (call,)), Message("tool", "héllo", tool_call_id="c1"),
        ], [ECHO])
        body = self.service.requests[0]
        self.assertEqual((body["model"], body["stream"]), ("fake-model", True))
        self.assertEqual(self.service.headers[0]["authorization"], "Bearer sk-test")
        self.assertEqual(body["tools"][0]["function"]["name"], "echo")
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "tool"])
        assistant = body["messages"][2]
        self.assertIsNone(assistant["content"])
        self.assertEqual(assistant["tool_calls"][0]["function"], {"name": "echo", "arguments": '{"text": "héllo"}'})
        self.assertEqual(body["messages"][3], {"role": "tool", "tool_call_id": "c1", "content": "héllo"})

    def test_no_tools_key_and_no_auth_header_when_not_needed(self) -> None:
        self.service.replies.append(chunks_for("ok"))
        list(OpenAICompatibleProvider(self.service.base_url + "/", "m").stream(
            [Message("user", "x")], [], threading.Event()))
        self.assertNotIn("tools", self.service.requests[0])
        self.assertNotIn("authorization", self.service.headers[0])

    def test_fragmented_parallel_tool_calls_are_reassembled(self) -> None:
        self.service.replies.append(chunks_for(tool_calls=[
            ("a", "echo", '{"text": "one"}'), ("b", "echo", '{"text": "two", "n": 2}')]))
        calls = [e.call for e in self.run_stream(tools=[ECHO]) if isinstance(e, ToolCallReady)]
        self.assertEqual(calls, [ToolCall("a", "echo", {"text": "one"}), ToolCall("b", "echo", {"text": "two", "n": 2})])

    def test_calls_without_an_index_are_kept_apart_by_id(self) -> None:
        # Gemini's OpenAI-compatible stream, as captured: each call whole, with an id and no index.
        self.service.replies.append([
            {"choices": [{"delta": {"tool_calls": [{"id": "call_1", "type": "function",
                                                    "function": {"name": "active_window", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"id": "call_2", "type": "function", "function": {
                "name": "search_software", "arguments": '{"query":"terminal"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}])
        # A service that numbers every call 0, and continues one in a fragment with neither id nor index.
        self.service.replies.append([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "echo", "arguments": "{}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "b", "function": {
                "name": "echo", "arguments": '{"text": '}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": '"two"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}])
        gemini = [e.call for e in self.run_stream(tools=[ECHO]) if isinstance(e, ToolCallReady)]
        self.assertEqual(gemini, [ToolCall("call_1", "active_window", {}),
                                  ToolCall("call_2", "search_software", {"query": "terminal"})])
        reused = [e.call for e in self.run_stream(tools=[ECHO]) if isinstance(e, ToolCallReady)]
        self.assertEqual(reused, [ToolCall("a", "echo", {}), ToolCall("b", "echo", {"text": "two"})])

    def test_bad_or_empty_tool_arguments_are_reported_not_fatal(self) -> None:
        self.service.replies.append(chunks_for(tool_calls=[("a", "echo", '{"text": '), ("b", "echo", "[1]")]))
        self.service.replies.append([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "", "function": {"name": "echo"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}])
        first = [e.call for e in self.run_stream() if isinstance(e, ToolCallReady)]
        self.assertIn("not valid JSON", first[0].arguments_error)
        self.assertIn("JSON object", first[1].arguments_error)
        empty = [e.call for e in self.run_stream() if isinstance(e, ToolCallReady)]
        self.assertEqual(empty, [ToolCall("call_0", "echo", {})])

    def test_http_errors_become_clear_messages(self) -> None:
        cases = {401: "rejected the API key", 404: "not found", 429: "rate limiting", 500: "HTTP 500"}
        for status, expected in cases.items():
            self.service.replies.append((status, {"error": {"message": "detail-from-service"}}))
            with self.subTest(status=status), self.assertRaisesRegex(ProviderError, expected) as caught:
                self.run_stream()
            self.assertIn("detail-from-service", str(caught.exception))

    def test_stream_options_rejection_is_retried_without_it(self) -> None:
        self.service.replies.append((400, {"error": {"message": "unknown field stream_options"}}))
        self.service.replies.append(chunks_for("fine"))
        self.assertEqual("".join(e.text for e in self.run_stream() if isinstance(e, TextDelta)), "fine")
        self.assertIn("stream_options", self.service.requests[0])
        self.assertNotIn("stream_options", self.service.requests[1])

    def test_error_event_inside_stream_and_unreachable_service(self) -> None:
        self.service.replies.append([{"error": {"message": "context length exceeded"}}])
        with self.assertRaisesRegex(ProviderError, "context length exceeded"):
            self.run_stream()
        dead = OpenAICompatibleProvider("http://127.0.0.1:9/v1", "m", timeout=2)
        with self.assertRaisesRegex(ProviderError, "Could not reach the model"):
            list(dead.stream([Message("user", "x")], [], threading.Event()))

    def test_cancel_stops_the_stream_and_drops_tool_calls(self) -> None:
        self.service.replies.append(chunks_for("x" * 200, tool_calls=[("a", "echo", "{}")]))
        cancel = threading.Event()
        events = []
        for event in self.provider.stream([Message("user", "x")], [ECHO], cancel):
            events.append(event)
            cancel.set()
        self.assertEqual(events[-1].stop_reason, "cancelled")
        self.assertFalse([e for e in events if isinstance(e, ToolCallReady)])

    def test_list_models_reports_context_windows_and_bad_addresses(self) -> None:
        self.assertEqual(list_models(self.service.base_url, "sk-test"),
                         [{"id": "fake-model", "context_window": 4096}, {"id": "other", "context_window": 0}])
        with self.assertRaisesRegex(ProviderError, "not found"):
            list_models(self.service.base_url.removesuffix("/v1"))
        self.service.models = {"unexpected": True}
        with self.assertRaisesRegex(ProviderError, "did not answer like a model service"):
            list_models(self.service.base_url)

    def test_a_port_that_does_not_speak_http_is_reported_as_unreachable(self) -> None:
        import socket

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = listener.getsockname()[1]

        def banner() -> None:
            for _ in range(2):
                try:
                    connection, _address = listener.accept()
                    connection.sendall(b"SSH-2.0-NotHttp\r\n")
                    connection.close()
                except OSError:
                    return

        thread = threading.Thread(target=banner, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(ProviderError, "Could not reach a model service"):
                list_models(f"http://127.0.0.1:{port}/v1", timeout=3)
            with self.assertRaisesRegex(ProviderError, "Could not reach the model"):
                list(OpenAICompatibleProvider(f"http://127.0.0.1:{port}/v1", "m", timeout=3).stream(
                    [Message("user", "x")], [], threading.Event()))
        finally:
            listener.close()
            thread.join(timeout=3)

    def test_create_provider_rejects_unknown_kinds(self) -> None:
        with self.assertRaisesRegex(ProviderError, "unknown model provider"):
            create_provider({"provider": "mystery"})


class ScriptedProvider:
    """Yields pre-written events per request and records what it was sent."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.seen: list[list[Message]] = []

    def stream(self, messages, tools, cancel):
        self.seen.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        yield from reply
        yield TurnEnd("stop")


def call(call_id: str, name: str, **arguments) -> ToolCallReady:
    return ToolCallReady(ToolCall(call_id, name, arguments))


class AgentLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ran: list[dict] = []
        self.cancel = threading.Event()

        def echo(arguments: dict) -> str:
            self.ran.append(arguments)
            return f"echo: {arguments.get('text', '')}"

        def broken(arguments: dict) -> str:
            raise ToolFailure("disk is unplugged")

        def stopper(arguments: dict) -> str:
            self.cancel.set()
            return "stopping"

        self.registry = ToolRegistry([
            Tool("echo", "Echo.", object_schema(), RISK_READ, echo),
            Tool("broken", "Fails.", object_schema(), RISK_READ, broken),
            Tool("stopper", "Cancels.", object_schema(), RISK_READ, stopper),
        ])
        self.events: list[dict] = []
        self.history = [Message("system", "s"), Message("user", "do it")]

    def run_loop(self, provider, **kwargs) -> None:
        run_turn(provider, self.history, self.registry, self.events.append, self.cancel, **kwargs)

    def kinds(self) -> list[str]:
        return [event["type"] for event in self.events]

    def assert_history_valid(self) -> None:
        """Every assistant tool call is answered by exactly one following tool message."""
        open_calls: list[str] = []
        for message in self.history:
            if message.role == "tool":
                self.assertIn(message.tool_call_id, open_calls)
                open_calls.remove(message.tool_call_id)
            else:
                self.assertEqual(open_calls, [], f"unanswered tool calls before {message.role}")
                open_calls = [item.id for item in message.tool_calls]
        self.assertEqual(open_calls, [])

    def test_plain_answer(self) -> None:
        self.run_loop(ScriptedProvider([ThinkingDelta(), ThinkingDelta(), TextDelta("Hi "), TextDelta("there")]))
        self.assertEqual(self.kinds(), ["thinking", "text_delta", "text_delta", "done"])
        self.assertEqual(self.history[-1], Message("assistant", "Hi there"))
        self.assertEqual(self.events[-1]["stop"], "answered")

    def test_tools_run_in_order_and_results_reach_the_model(self) -> None:
        provider = ScriptedProvider(
            [TextDelta("Checking. "), call("1", "echo", text="a"), call("2", "echo", text="b")],
            [TextDelta("Done.")])
        self.run_loop(provider)
        self.assertEqual(self.kinds(), ["text_delta", "tool_call", "tool_result", "tool_call", "tool_result",
                                        "text_delta", "done"])
        self.assertEqual(self.ran, [{"text": "a"}, {"text": "b"}])
        self.assertEqual(self.events[1]["risk"], "read")
        second_request = provider.seen[1]
        self.assertEqual([m.role for m in second_request], ["system", "user", "assistant", "tool", "tool"])
        self.assertEqual([m.text for m in second_request[-2:]], ["echo: a", "echo: b"])
        self.assert_history_valid()

    def test_how_can_i_question_blocks_unrequested_delete_before_approval(self):
        self.history[-1] = Message("user", "How can I clear the trash on my storage drive?")
        self.registry = self.registry.with_tools([
            Tool("delete", "Delete.", object_schema(), RISK_DANGER, self.ran.append)])
        self.run_loop(ScriptedProvider([call("1", "delete"), call("2", "echo", text="inspect")],
                                       [TextDelta("Open Trash in Dolphin.")]))
        self.assertEqual(self.ran, [{"text": "inspect"}])
        self.assertFalse(next(e for e in self.events if e["type"] == "tool_result")["ok"])

    def test_a_tool_card_travels_with_its_successful_result_only(self) -> None:
        self.registry = ToolRegistry([
            Tool("echo", "Echo.", object_schema(), RISK_READ, lambda a: "sunny", card=lambda text: {"kind": "weather", "now": text}),
            Tool("broken", "Fails.", object_schema(), RISK_READ, lambda a: (_ for _ in ()).throw(ToolFailure("offline")),
                 card=lambda text: {"kind": "weather"}),
        ])
        self.run_loop(ScriptedProvider([call("1", "echo"), call("2", "broken")], [TextDelta("Done.")]))
        results = {event["id"]: event for event in self.events if event["type"] == "tool_result"}
        self.assertEqual(results["1"]["card"], {"kind": "weather", "now": "sunny"})
        self.assertNotIn("card", results["2"])

    def test_tool_failures_and_bad_calls_are_returned_to_the_model(self) -> None:
        bad_arguments = ToolCallReady(ToolCall("3", "echo", {}, "arguments were not valid JSON"))
        self.run_loop(ScriptedProvider(
            [call("1", "broken"), call("2", "missing_tool"), bad_arguments], [TextDelta("Sorry.")]))
        results = [event for event in self.events if event["type"] == "tool_result"]
        self.assertEqual([result["ok"] for result in results], [False, False, False])
        self.assertIn("disk is unplugged", results[0]["text"])
        self.assertIn("no tool named 'missing_tool'", results[1]["text"])
        self.assertIn("not valid JSON", results[2]["text"])
        self.assertEqual(self.ran, [])
        self.assertEqual(done_core(self.events[-1]), {"type": "done", "stop": "answered", "actions": []})
        self.assert_history_valid()

    def test_a_dangerous_step_that_succeeded_is_not_repeated_but_a_failed_one_can_be(self) -> None:
        installs: list[dict] = []

        def install(arguments: dict) -> str:
            installs.append(arguments)
            if arguments.get("fail"):
                raise ToolFailure("[exit status 1]")
            return "[exit status 0]"

        self.registry = ToolRegistry([*(self.registry.get(name) for name in ("echo",)),
                                      Tool("install", "Installs.", object_schema(), RISK_DANGER, install)])
        provider = ScriptedProvider(
            [call("1", "install", package="a"), call("2", "echo", text="x")],
            [call("3", "install", package="a"), call("4", "echo", text="x")],
            [call("5", "install", package="b", fail=True)],
            [call("6", "install", package="b", fail=True), call("7", "install", package="c")],
            [TextDelta("Done.")])
        self.run_loop(provider)
        self.assertEqual(installs, [{"package": "a"}, {"package": "b", "fail": True},
                                    {"package": "b", "fail": True}, {"package": "c"}])
        self.assertEqual(self.ran, [{"text": "x"}, {"text": "x"}], "read steps may repeat")
        results = {event["id"]: event for event in self.events if event["type"] == "tool_result"}
        self.assertFalse(results["3"]["ok"])
        self.assertIn("already succeeded", results["3"]["text"])
        self.assertTrue(results["7"]["ok"])
        self.assert_history_valid()

    def test_step_limit_stops_a_model_that_never_answers(self) -> None:
        provider = ScriptedProvider(*[[call(str(index), "echo", text="x")] for index in range(10)])
        self.run_loop(provider, max_steps=3)
        self.assertEqual(done_core(self.events[-1]), {"type": "done", "stop": "step_limit", "actions": []})
        self.assertEqual(len(provider.seen), 3)
        self.assert_history_valid()

    def test_provider_failure_leaves_history_untouched(self) -> None:
        before = list(self.history)
        self.run_loop(ScriptedProvider(ProviderError("The model service rejected the API key.")))
        self.assertEqual(self.events, [{"type": "error", "message": "The model service rejected the API key."}])
        self.assertEqual(self.history, before)

    def test_failure_after_tools_keeps_the_completed_step(self) -> None:
        self.run_loop(ScriptedProvider([call("1", "echo", text="a")], ProviderError("connection lost")))
        self.assertEqual(self.kinds(), ["tool_call", "tool_result", "error"])
        self.assert_history_valid()

    def test_cancel_during_tools_skips_the_rest_but_answers_every_call(self) -> None:
        self.run_loop(ScriptedProvider([call("1", "stopper"), call("2", "echo", text="never")], [TextDelta("no")]))
        self.assertEqual(self.ran, [])
        self.assertEqual(done_core(self.events[-1]), {"type": "done", "stop": "cancelled", "actions": []})
        self.assertEqual(self.history[-1].text, "Not run: the user cancelled.")
        self.assert_history_valid()

    def test_cancel_before_start_and_during_stream(self) -> None:
        self.cancel.set()
        self.run_loop(ScriptedProvider([TextDelta("x")]))
        self.assertEqual([done_core(event) for event in self.events], [{"type": "done", "stop": "cancelled", "actions": []}])
        self.assertEqual(len(self.history), 2)

    def test_tools_can_report_progress_and_it_is_throttled(self) -> None:
        from happy_bot.tools.registry import report_progress

        def chatty(arguments: dict) -> str:
            for index in range(50):
                report_progress(f"line {index}")
            return "done"

        self.registry = ToolRegistry([Tool("chatty", "x", object_schema(), RISK_READ, chatty)])
        self.run_loop(ScriptedProvider([call("1", "chatty")], [TextDelta("ok")]))
        progress = [event for event in self.events if event["type"] == "tool_progress"]
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0], {"type": "tool_progress", "id": "1", "text": "line 0"})
        report_progress("outside a call is ignored")

    def test_tool_bugs_do_not_end_the_turn_and_long_results_are_cut(self) -> None:
        registry = ToolRegistry([
            Tool("crash", "x", object_schema(), RISK_READ, lambda a: 1 / 0),
            Tool("flood", "x", object_schema(), RISK_READ, lambda a: "z" * 50000),
        ])
        ok, text = registry.run("crash", {})
        self.assertEqual((ok, "ZeroDivisionError" in text), (False, True))
        ok, text = registry.run("flood", {})
        self.assertTrue(ok and len(text) < 8200 and "more characters not shown" in text)
        with self.assertRaises(ValueError):
            ToolRegistry([Tool("bad name", "x", object_schema(), RISK_READ, str)])


class TrimHistoryTests(unittest.TestCase):
    def test_short_history_is_untouched(self) -> None:
        history = [Message("system", "s"), Message("user", "a"), Message("assistant", "b")]
        self.assertEqual(trim_history(history, 32768), history)

    def test_oldest_whole_turns_are_dropped_and_tool_pairs_stay_together(self) -> None:
        big = "x" * 3000
        tool_call = ToolCall("1", "echo", {})
        history = [
            Message("system", "s"),
            Message("user", "first"), Message("assistant", "", (tool_call,)), Message("tool", big, tool_call_id="1"),
            Message("assistant", big),
            Message("user", "second"), Message("assistant", big),
            Message("user", "third"),
        ]
        trimmed = trim_history(history, 2048)
        self.assertEqual([m.text for m in trimmed if m.role == "user"], ["second", "third"])
        self.assertEqual(trimmed[0].role, "system")
        self.assertFalse([m for m in trimmed if m.role == "tool"])

    def test_latest_turn_survives_even_when_too_large(self) -> None:
        history = [Message("system", "s"), Message("user", "old"), Message("user", "y" * 100000)]
        self.assertEqual([m.text[:3] for m in trim_history(history, 1024)], ["s", "Ear", "yyy"])

    def test_dropped_turns_leave_a_digest_of_requests_tools_and_answers(self) -> None:
        big = "x" * 3000
        call = ToolCall("1", "disk_usage", {})
        history = [Message("system", "s"), Message("user", "How full is my disk?"),
                   Message("assistant", "", (call,)), Message("tool", big, tool_call_id="1"),
                   Message("assistant", "It is 61% full. " + big), Message("user", "and now?")]
        digest = trim_history(history, 1024)[1]
        self.assertEqual(digest.role, "system")
        self.assertIn("The user asked: How full is my disk? (tools used: disk_usage); you answered: It is 61% full.",
                      digest.text)


if __name__ == "__main__":
    unittest.main()
