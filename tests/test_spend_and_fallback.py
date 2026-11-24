"""Tests for spending records, the monthly cap, prices in settings, and the local fallback model.

The ledger is written into the test process's private data folder
(``isolation``). The fallback is checked with scripted providers: a first
model that fails before producing anything, and a local fallback that
answers; a hosted fallback must never be used.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant import ask_stream, spend  # noqa: E402
from kde_ai_assistant.conversation import Message, TextDelta, TurnEnd  # noqa: E402
from kde_ai_assistant.providers.base import ProviderError  # noqa: E402
from kde_ai_assistant.settings import SettingsError, validate_settings  # noqa: E402
from kde_ai_assistant.tools.registry import ToolRegistry  # noqa: E402

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
        self.assertTrue(spend.over_cap(hosted, 4))
        self.assertFalse(spend.over_cap(hosted, 0))
        self.assertFalse(spend.over_cap(LOCAL, 4))

    def test_prices_and_fallback_are_validated(self) -> None:
        with self.assertRaisesRegex(SettingsError, "'input_price'"):
            validate_settings({"models": {"m": {**HOSTED, "input_price": -1}}})
        with self.assertRaisesRegex(SettingsError, "fallback model 'ghost' is not set up"):
            validate_settings({"models": {"m": LOCAL}, "agent": {"fallback_model": "ghost"}})
        with self.assertRaisesRegex(SettingsError, "'monthly_spend_cap'"):
            validate_settings({"agent": {"monthly_spend_cap": "lots"}})


class Failing:
    def stream(self, messages, tools, cancel):
        raise ProviderError("connection refused")
        yield  # pragma: no cover


class Answering:
    def stream(self, messages, tools, cancel):
        yield TextDelta("hello")
        yield TurnEnd("stop", 10, 2)


class FallbackTests(unittest.TestCase):
    class Conversation:
        def __init__(self) -> None:
            self.history = [Message("user", "hi")]
            self.cancel = threading.Event()

    def test_only_a_different_local_model_is_a_fallback(self) -> None:
        settings = validate_settings({"models": {"big": HOSTED, "small": LOCAL, "other": {**HOSTED, "model": "x"}},
                                      "agent": {"fallback_model": "small"}})
        self.assertEqual(ask_stream._fallback(settings, "big"), "small")
        self.assertEqual(ask_stream._fallback(settings, "small"), "")
        settings["agent"]["fallback_model"] = "other"
        self.assertEqual(ask_stream._fallback(settings, "big"), "")

    def test_an_early_failure_is_held_for_the_fallback_and_usage_is_reported(self) -> None:
        conversation, events = self.Conversation(), []
        agent = validate_settings({})["agent"]
        held = ask_stream._attempt(Failing(), "big", HOSTED, conversation, ToolRegistry([]), events.append, None, agent,
                                   hold_first_error=True)
        self.assertIn("connection refused", held["message"])
        self.assertEqual(events, [])
        self.assertEqual(len(conversation.history), 1)
        held = ask_stream._attempt(Answering(), "small", LOCAL, conversation, ToolRegistry([]), events.append, None,
                                   agent, hold_first_error=False)
        self.assertIsNone(held)
        done = events[-1]
        self.assertEqual((done["model"], done["usage"]["input_tokens"], done["cost"]), ("small", 10, 0.0))



class BusyModelTests(unittest.TestCase):
    def test_all_slots_busy_is_reported_and_anything_odd_is_not(self) -> None:
        from unittest import mock

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
