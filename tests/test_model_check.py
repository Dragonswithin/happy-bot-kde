"""Tests for model_check: how each compatibility check judges a model's replies.

The provider is replaced by a scripted one that answers each request from a list, so these check
the verdicts (pass, warn, fail, skip) and that a broken or merged tool call is a failure, the bug
class the check exists for. No model is contacted.
"""

from __future__ import annotations

import sys
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import model_check  # noqa: E402
from happy_bot.conversation import TextDelta, ToolCall, ToolCallReady, TurnEnd  # noqa: E402
from happy_bot.providers import ProviderError  # noqa: E402

LOCAL = {"provider": "openai_compatible", "base_url": "http://127.0.0.1:1/v1", "model": "m"}


class ScriptedProvider:
    """Answers request N with ``replies[N]``: a list of events, or a ProviderError to raise."""

    def __init__(self, replies: list) -> None:
        self.replies, self.requests = list(replies), []

    def stream(self, messages, tools, cancel):
        self.requests.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        yield from reply
        yield TurnEnd(stop_reason="stop", input_tokens=5, output_tokens=2)


def text(words: str) -> list:
    return [TextDelta(words)]


def calls(*items: ToolCall) -> list:
    return [ToolCallReady(item) for item in items]


WEATHER = ToolCall("w1", "get_weather", {"city": "Paris", "units": {"system": "metric"}})
CLOCK = ToolCall("t1", "get_time", {"zone": "Asia/Tokyo"})


def run(replies: list, model: dict | None = None) -> dict[str, dict]:
    provider = ScriptedProvider(replies)
    with mock.patch.object(model_check, "create_provider", return_value=provider):
        return {result["check"]: result for result in model_check.run(model or LOCAL)}


class ModelCheckTests(unittest.TestCase):
    def test_a_model_that_does_everything_passes(self) -> None:
        results = run([text("ready"), calls(WEATHER), calls(WEATHER, CLOCK), text("17 degrees, report 4242"),
                       text("Report 4242."), text("Red")], {**LOCAL, "vision": True})
        self.assertEqual({check: result["status"] for check, result in results.items()},
                         {"answers": "pass", "tool_call": "pass", "parallel_calls": "pass", "tool_result": "pass",
                          "handover": "pass", "picture": "pass"})

    def test_merged_or_broken_calls_fail_and_one_at_a_time_only_warns(self) -> None:
        glued = ToolCall("w1", "get_weather", {}, "arguments were not valid JSON (Extra data)")
        results = run([text("ready"), calls(WEATHER), calls(glued), text("4242"), text("4242")])
        self.assertEqual(results["parallel_calls"]["status"], "fail")
        self.assertIn("Extra data", results["parallel_calls"]["detail"])
        self.assertEqual(results["picture"]["status"], "skip")
        sequential = run([text("ready"), calls(WEATHER), calls(WEATHER), text("4242"), text("4242")])
        self.assertEqual(sequential["parallel_calls"]["status"], "warn")

    def test_refusals_fail_with_the_reason_and_later_checks_still_run(self) -> None:
        results = run([text("ready"), calls(WEATHER), calls(WEATHER, CLOCK),
                       ProviderError("missing thought signature"), ProviderError("HTTP 400")])
        self.assertEqual(results["tool_result"]["status"], "fail")
        self.assertIn("missing thought signature", results["tool_result"]["detail"])
        self.assertEqual(results["handover"]["status"], "fail")
        unreachable = run([ProviderError("Could not reach the model")])
        self.assertEqual(list(unreachable), ["answers"])

    def test_no_tool_use_warns_and_skips_the_result_check(self) -> None:
        results = run([text("ready"), text("It is sunny."), text("Sunny."), text("4242")])
        self.assertEqual(results["tool_call"]["status"], "warn")
        self.assertEqual(results["tool_result"]["status"], "skip")

    def test_the_tool_result_goes_back_with_the_models_own_call(self) -> None:
        provider = ScriptedProvider([text("ready"), calls(WEATHER), calls(WEATHER, CLOCK), text("4242"), text("4242")])
        with mock.patch.object(model_check, "create_provider", return_value=provider):
            model_check.run(LOCAL)
        sent = provider.requests[3]
        self.assertEqual(sent[-3].tool_calls, (WEATHER,))
        self.assertEqual((sent[-2].role, sent[-2].tool_call_id, sent[-2].text), ("tool", "w1", model_check.WEATHER_RESULT))

    def test_the_test_picture_is_a_valid_png(self) -> None:
        data = model_check._png((220, 20, 20), size=4)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        start = data.index(b"IDAT") + 4
        length = int.from_bytes(data[start - 8:start - 4], "big")
        self.assertEqual(zlib.decompress(data[start:start + length])[:4], b"\x00\xdc\x14\x14")


if __name__ == "__main__":
    unittest.main()
