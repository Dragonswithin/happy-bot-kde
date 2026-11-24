"""Tests for the OpenAI Responses API provider (``providers.openai_responses``).

The HTTP call is replaced by a stand-in that records the request body and returns server-sent
event lines shaped like the ones OpenAI documents (output text deltas, a function call added, its
argument deltas and done, ``response.completed`` with usage and the full output), so nothing goes
online. Checked: text and tool calls come out as the agent loop expects; the next request replays
that response's output items (reasoning included) before the tool result; history from another
model is sent as plain items; and a failure event becomes a ``ProviderError``.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.conversation import Message, TextDelta, ToolCall, ToolCallReady, ToolSpec, TurnEnd  # noqa: E402
from happy_bot.providers import ProviderError, create_provider  # noqa: E402
from happy_bot.providers import openai_responses  # noqa: E402

BASE = "https://api.openai.com/v1"
REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"}
CALL = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "weather", "arguments": '{"place": "Oslo"}'}


class FakeStream:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.lines = [f"data: {json.dumps(event)}\n".encode() for event in events]

    def __iter__(self):
        return iter(self.lines)

    def close(self) -> None:
        pass


class ResponsesProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = create_provider({"provider": "openai_responses", "base_url": BASE, "model": "gpt-6-luna",
                                         "api_key": "k"})
        self.sent: list[dict[str, Any]] = []

    def run_stream(self, events: list[dict[str, Any]], messages: list[Message], tools=()) -> list[Any]:
        def fake_urlopen(request, timeout=None):
            self.sent.append(json.loads(request.data))
            self.assertTrue(request.full_url.endswith("/responses"))
            return FakeStream(events)
        with mock.patch.object(openai_responses, "urlopen", side_effect=fake_urlopen):
            return list(self.provider.stream(messages, list(tools), threading.Event()))

    def test_a_tool_call_streams_and_its_reasoning_comes_back_next_time(self) -> None:
        events = [
            {"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning", "id": "rs_1"}},
            {"type": "response.output_item.done", "output_index": 0, "item": REASONING},
            {"type": "response.output_item.added", "output_index": 1, "item": {**CALL, "arguments": ""}},
            {"type": "response.function_call_arguments.delta", "output_index": 1, "item_id": "fc_1", "delta": '{"place": '},
            {"type": "response.function_call_arguments.delta", "output_index": 1, "item_id": "fc_1", "delta": '"Oslo"}'},
            {"type": "response.output_item.done", "output_index": 1, "item": CALL},
            {"type": "response.completed", "response": {"output": [REASONING, CALL],
                                                        "usage": {"input_tokens": 30, "output_tokens": 9}}},
        ]
        tool = ToolSpec("weather", "Weather.", {"type": "object", "properties": {"place": {"type": "string"}}})
        history = [Message("system", "be brief"), Message("user", "weather in Oslo?")]
        out = self.run_stream(events, history, [tool])
        calls = [event.call for event in out if isinstance(event, ToolCallReady)]
        self.assertEqual([(call.id, call.name, call.arguments) for call in calls], [("call_1", "weather", {"place": "Oslo"})])
        end = out[-1]
        self.assertIsInstance(end, TurnEnd)
        self.assertEqual((end.input_tokens, end.output_tokens), (30, 9))
        first = self.sent[0]
        self.assertEqual((first["instructions"], first["store"], first["input"]),
                         ("be brief", False, [{"role": "user", "content": "weather in Oslo?"}]))
        self.assertEqual(first["tools"][0], {"type": "function", "name": "weather", "description": "Weather.",
                                             "parameters": tool.parameters, "strict": False})

        history += [Message("assistant", "", tuple(calls), echo=end.echo), Message("tool", "sunny", tool_call_id="call_1")]
        self.run_stream([{"type": "response.output_text.delta", "delta": "Sunny."},
                         {"type": "response.completed", "response": {"usage": {}}}], history)
        replayed = self.sent[1]["input"]
        self.assertEqual(replayed[1:], [REASONING, CALL, {"type": "function_call_output", "call_id": "call_1",
                                                          "output": "sunny"}])

    def test_history_from_another_model_is_sent_as_plain_items(self) -> None:
        history = [Message("user", "hi"), Message("assistant", "Hello", (ToolCall("c9", "note", {"x": 1}),)),
                   Message("tool", "ok", tool_call_id="c9")]
        out = self.run_stream([{"type": "response.output_text.delta", "delta": "Done"},
                               {"type": "response.completed", "response": {"usage": {}}}], history)
        self.assertEqual("".join(event.text for event in out if isinstance(event, TextDelta)), "Done")
        self.assertEqual(self.sent[0]["input"][1:], [
            {"role": "assistant", "content": "Hello"},
            {"type": "function_call", "call_id": "c9", "name": "note", "arguments": '{"x": 1}'},
            {"type": "function_call_output", "call_id": "c9", "output": "ok"},
        ])

    def test_a_failure_event_is_reported(self) -> None:
        with self.assertRaisesRegex(ProviderError, "quota exceeded"):
            self.run_stream([{"type": "response.failed", "response": {"error": {"message": "quota exceeded"}}}],
                            [Message("user", "hi")])


if __name__ == "__main__":
    unittest.main()
