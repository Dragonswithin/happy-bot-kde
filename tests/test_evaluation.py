"""Tests for the model evaluation (``evaluation.run``) with scripted event streams."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import evaluation  # noqa: E402


class EvaluationTests(unittest.TestCase):
    def test_pass_needs_an_expected_tool_and_an_answer(self) -> None:
        def stream(request, model):
            if request == "What time is it?":
                yield {"type": "tool_call", "name": "current_time"}
                yield {"type": "text_delta", "text": "It is 14:05."}
            elif "roadmap" in request:
                yield {"type": "tool_call", "name": "index__search"}
                yield {"type": "text_delta", "text": "Found it."}
            elif "clipboard" in request:
                yield {"type": "text_delta", "text": "I cannot see it."}
            else:
                yield {"type": "error", "message": "model unreachable"}

        results = {item["request"]: item for item in evaluation.run(stream, "m", "index__search")}
        self.assertTrue(results["What time is it?"]["passed"])
        self.assertTrue(results["Find documents about the roadmap on my computer."]["passed"])
        self.assertEqual(results["What is on my clipboard?"]["problem"], "did not use clipboard_history or clipboard_text")
        self.assertEqual(results["Which window am I working in?"]["problem"], "model unreachable")
        self.assertEqual(len(results), len(evaluation.SCENARIOS))


if __name__ == "__main__":
    unittest.main()
