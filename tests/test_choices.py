"""Tests for the assistant's answer buttons (``tools/choices.py``) and the turn ending after them.

The tools are called directly and their text read back into the card the popup draws; then a
scripted provider (``test_provider_and_agent_loop.ScriptedProvider``) asks a question with
buttons, and the agent loop must stop there instead of asking the model again. Nothing is sent
to a real model.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot.agent_loop import run_turn  # noqa: E402
from happy_bot.conversation import Message, TextDelta  # noqa: E402
from happy_bot.tools import choices  # noqa: E402
from happy_bot.tools.registry import ToolFailure, ToolRegistry  # noqa: E402
from test_provider_and_agent_loop import ScriptedProvider, call  # noqa: E402


class ChoiceToolTests(unittest.TestCase):
    def test_a_question_becomes_a_card_of_buttons(self) -> None:
        text = choices.ask_user({"question": "Which  edition?", "choices": ["Java | mods", "Bedrock", "Bedrock", " "]})
        self.assertEqual(choices.choices_card(text), {"kind": "choices", "question": "Which edition?",
                                                      "choices": ["Java / mods", "Bedrock"], "follow_up": False})
        self.assertIn("Stop now", text)

    def test_suggestions_are_follow_ups(self) -> None:
        card = choices.choices_card(choices.suggest_next({"suggestions": ["Open Prism Launcher", "x" * 90]}))
        self.assertEqual(card["follow_up"], True)
        self.assertEqual(card["choices"], ["Open Prism Launcher", "x" * choices.MAX_CHOICE_CHARS])

    def test_bad_calls_are_refused_and_other_text_has_no_card(self) -> None:
        for bad in ({"question": "Which?", "choices": ["only one"]}, {"question": "", "choices": ["a", "b"]},
                    {"question": "Which?", "choices": ["a", "b", "c", "d", "e"]}, {"question": "Which?", "choices": "a, b"}):
            with self.assertRaises(ToolFailure):
                choices.ask_user(bad)
        with self.assertRaises(ToolFailure):
            choices.suggest_next({"suggestions": []})
        self.assertIsNone(choices.choices_card("Paris: now 17°C"))


class EndsTurnTests(unittest.TestCase):
    def test_the_turn_stops_after_buttons_are_shown(self) -> None:
        provider = ScriptedProvider(
            [TextDelta("Two launchers fit. "), call("c1", "ask_user", question="Which edition?", choices=["Java", "Bedrock"])],
            [TextDelta("never asked")])
        events: list[dict] = []
        history = [Message("system", "test"), Message("user", "minecraft")]
        run_turn(provider, history, ToolRegistry(choices.choice_tools()), events.append, threading.Event())
        self.assertEqual(len(provider.seen), 1)                       # the model was not asked again
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["stop"], "answered")
        result = next(event for event in events if event["type"] == "tool_result")
        self.assertEqual(result["card"]["choices"], ["Java", "Bedrock"])
        self.assertEqual([message.role for message in history][-2:], ["assistant", "tool"])  # a valid history


if __name__ == "__main__":
    unittest.main()
