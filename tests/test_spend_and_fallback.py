"""Tests for spending records, each model's monthly limit, and asking models in the user's order.

The ledger is written into the test process's private data folder
(``isolation``). The order is checked with scripted providers: a model that
fails before producing anything (the next one answers instead), a model
that keeps calling tools and is marked to hand long requests on (the next
one continues the same history, and the final ``done`` reports every
action), and the conversion of settings from before the order existed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import ask_stream, spend  # noqa: E402
from happy_bot.conversation import Message, TextDelta, ToolCall, ToolCallReady, TurnEnd  # noqa: E402
from happy_bot.providers.base import ProviderError  # noqa: E402
from happy_bot.settings import SettingsError, validate_settings  # noqa: E402
from happy_bot.tools.registry import RISK_CHANGE, Tool, ToolRegistry, object_schema  # noqa: E402

LOCAL = {"provider": "openai_compatible", "base_url": "http://127.0.0.1:1/v1", "model": "small", "context_window": 32768}
HOSTED = {"provider": "openai_compatible", "base_url": "https://api.example.com/v1", "model": "big", "context_window": 32768,
          "input_price": 3, "output_price": 15}


class SpendTests(unittest.TestCase):
    def setUp(self) -> None:
        if spend.ledger_path().exists():
            spend.ledger_path().unlink()

    def test_cost_is_recorded_per_month_and_the_cap_stops_priced_models_only(self) -> None:
        hosted = validate_settings({"models": {"big": HOSTED}})["models"]["big"]
        self.assertAlmostEqual(spend.record("big", hosted, 1_000_000, 100_000), 4.5)
        spend.record("small", LOCAL, 5000, 500)
        summary = spend.month_summary()
        self.assertEqual(summary["total_cost"], 4.5)
        self.assertEqual(summary["models"]["small"]["input_tokens"], 5000)
        self.assertTrue(spend.over_cap("big", {**hosted, "monthly_cap": 4}))
        self.assertFalse(spend.over_cap("big", hosted))
        self.assertFalse(spend.over_cap("other", {**hosted, "monthly_cap": 4}))  # its own spending, not the total
        self.assertFalse(spend.over_cap("small", {**LOCAL, "monthly_cap": 0.001}))

    def test_clear_past_usage_preserves_current_caps_and_ignores_future_months(self) -> None:
        hosted = {**HOSTED, "monthly_cap": 4}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            with mock.patch.object(spend, "_month", return_value="2025-12"):
                spend.record("big", hosted, 2000, 100, path)
            with mock.patch.object(spend, "_month", return_value="2026-02"):
                spend.record("big", hosted, 600, 20, path)
            with mock.patch.object(spend, "_month", return_value="2026-01"):
                spend.record("big", hosted, 1_500_000, 100, path)
                before = json.loads(path.read_text())
                self.assertTrue(spend.over_cap("big", hosted, path))
                spend.clear_past_usage(path)
                spend.clear_past_usage(path)
                del before["2025-12"]
                self.assertEqual(json.loads(path.read_text()), before)
                self.assertTrue(spend.over_cap("big", hosted, path))
                spend.record("big", hosted, 200, 20, path)
                self.assertEqual(spend.month_summary(path)["models"]["big"]["input_tokens"], 1_500_200)

    def test_clear_usage_reports_errors_without_overwriting_and_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            spend.clear_past_usage(path)
            self.assertFalse(path.exists())
            path.write_text("{damaged")
            with self.assertRaises(OSError):
                spend.clear_past_usage(path)
            self.assertEqual(path.read_text(), "{damaged")
            with mock.patch.object(spend, "_month", return_value="2026-01"):
                previous = '{"2025-12": {}, "2026-01": {}}'
                path.write_text(previous)
                with mock.patch.object(spend, "write_private_file", side_effect=OSError("full")):
                    with self.assertRaises(OSError):
                        spend.clear_past_usage(path)
                self.assertEqual(path.read_text(), previous)
                spend.clear_past_usage(path)
                self.assertEqual(json.loads(path.read_text()), {"2026-01": {}})

    def test_prices_and_limits_are_validated(self) -> None:
        with self.assertRaisesRegex(SettingsError, "'input_price'"):
            validate_settings({"models": {"m": {**HOSTED, "input_price": -1}}})
        with self.assertRaisesRegex(SettingsError, "'monthly_cap'"):
            validate_settings({"models": {"m": {**HOSTED, "monthly_cap": "lots"}}})
        with self.assertRaisesRegex(SettingsError, "'model_order' must be a list"):
            validate_settings({"models": {"m": LOCAL}, "model_order": "m"})

    def test_settings_from_before_the_order_are_converted(self) -> None:
        settings = validate_settings({"models": {"big": HOSTED, "small": LOCAL, "gpu": {**LOCAL, "model": "g"}},
                                      "active_model": "big",
                                      "agent": {"quick_model": "small", "fallback_model": "gpu", "monthly_spend_cap": 9}})
        self.assertEqual(settings["model_order"], ["big", "small", "gpu"])  # the active one stays first
        self.assertTrue(settings["models"]["small"]["hand_over_long"])
        self.assertEqual(settings["models"]["big"]["monthly_cap"], 9)
        self.assertNotIn("fallback_model", settings["agent"])
        unordered = validate_settings({"models": {"b": LOCAL, "a": LOCAL}, "model_order": ["b", "gone"]})
        self.assertEqual(unordered["model_order"], ["b", "a"])


class Failing:
    def stream(self, messages, tools, cancel):
        raise ProviderError("connection refused")
        yield  # pragma: no cover


class Answering:
    def stream(self, messages, tools, cancel):
        yield TextDelta("hello")
        yield TurnEnd("stop", 10, 2)


class Conversation:
    def __init__(self) -> None:
        self.history = [Message("user", "hi")]
        self.cancel = threading.Event()


class Looping:
    """A model that calls a tool on every step and never answers."""

    def __init__(self) -> None:
        self.step = 0

    def stream(self, messages, tools, cancel):
        self.step += 1
        yield ToolCallReady(ToolCall(str(self.step), "note", {}))
        yield TurnEnd("tool_calls", 5, 1)


def note_registry() -> ToolRegistry:
    return ToolRegistry([Tool("note", "Note.", object_schema(), RISK_CHANGE, lambda a: "noted",
                              summarize=lambda a: "Make a note")])


class ModelOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = validate_settings({})["agent"]

    def test_models_that_cannot_answer_are_skipped_with_a_reason(self) -> None:
        settings = validate_settings({"models": {"big": {**HOSTED, "monthly_cap": 1}, "small": LOCAL},
                                      "model_order": ["big", "small"], "agent": {"local_only": True}})
        chain, skipped = ask_stream._usable(settings, settings["model_order"])
        self.assertEqual([name for name, _, _ in chain], ["small"])
        self.assertIn("local only", skipped[0])

    def test_a_failure_goes_to_the_next_model_with_a_notice(self) -> None:
        conversation, events = Conversation(), []
        chain = [("big", HOSTED, Failing()), ("small", LOCAL, Answering())]
        ask_stream._run_chain(chain, conversation, ToolRegistry([]), events.append, None, self.agent)
        self.assertIn("big did not answer", next(event["message"] for event in events if event["type"] == "notice"))
        self.assertEqual([event["model"] for event in events if event["type"] == "context_usage"],
                         ["big", "small", "small"])
        done = events[-1]
        self.assertEqual((done["type"], done["model"], done["usage"]["input_tokens"]), ("done", "small", 10))

    def test_the_last_model_shows_its_own_failure(self) -> None:
        events = []
        ask_stream._run_chain([("small", LOCAL, Failing())], Conversation(), ToolRegistry([]), events.append, None,
                              self.agent)
        self.assertEqual(events[-1]["type"], "error")

    def test_a_long_request_is_handed_on_with_the_same_history_and_all_actions(self) -> None:
        conversation, events = Conversation(), []
        quick = {**LOCAL, "hand_over_long": True}
        chain = [("small", quick, Looping()), ("big", HOSTED, Answering())]
        ask_stream._run_chain(chain, conversation, note_registry(), events.append, None, self.agent)
        self.assertIn("small handed this to big", next(e["message"] for e in events if e["type"] == "notice"))
        done = events[-1]
        self.assertEqual((done["model"], len(done["actions"])), ("big", ask_stream.HAND_OVER_STEPS))
        self.assertEqual([e["type"] for e in events].count("done"), 1)


class BusyModelTests(unittest.TestCase):
    def test_all_slots_busy_is_reported_and_anything_odd_is_not(self) -> None:
        cases = [([{"is_processing": True}], True), ([{"is_processing": True}, {"is_processing": False}], False),
                 ({"error": "no slots"}, False), ([], False)]
        for slots, busy in cases:
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = __import__("json").dumps(slots).encode()
            with self.subTest(slots=slots), mock.patch.object(ask_stream.urllib.request, "urlopen", return_value=response):
                self.assertEqual(ask_stream.model_busy("http://127.0.0.1:1/v1"), busy)
        with mock.patch.object(ask_stream.urllib.request, "urlopen", side_effect=OSError("refused")):
            self.assertFalse(ask_stream.model_busy("http://127.0.0.1:1/v1"))


if __name__ == "__main__":
    unittest.main()
