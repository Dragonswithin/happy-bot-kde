"""Tests for the notes, to-do and memory tools.

Notes and to-dos are written for real into a temporary Documents folder;
the memory tools run against an in-memory settings store validated by the
real ``settings.py``. Undo is checked for each kind of change.
"""

from __future__ import annotations

import datetime
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from kde_ai_assistant.settings import SettingsError, validate_settings  # noqa: E402
from kde_ai_assistant.tools import undo  # noqa: E402
from kde_ai_assistant.tools.memory import memory_tools  # noqa: E402
from kde_ai_assistant.tools.notes import note_tools  # noqa: E402
from kde_ai_assistant.tools.registry import RISK_DANGER, ToolFailure  # noqa: E402


class Store:
    def __init__(self, raw: dict) -> None:
        self.settings = validate_settings(raw)

    def read(self) -> dict:
        return self.settings

    def update(self, mutate) -> dict:
        import copy
        changed = copy.deepcopy(self.settings)
        mutate(changed)
        self.settings = validate_settings(changed)
        return self.settings


class NoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.docs = Path(self._tmp.name)
        self.store = Store({"folders": {"Documents": str(self.docs)}})
        self.tools = {tool.name: tool for tool in note_tools(self.store.read)}

    def test_notes_are_appended_found_and_undone(self) -> None:
        self.tools["add_note"].handler({"text": "Fence quote $4,200 from Bob"})
        self.tools["add_note"].handler({"text": "Call the vet"})
        content = (self.docs / "Notes.md").read_text()
        self.assertRegex(content, r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} Fence quote \$4,200 from Bob\n")
        self.assertIn("Fence quote", self.tools["find_notes"].handler({"contains": "fence"}))
        undo.undo_change({})
        self.assertNotIn("vet", (self.docs / "Notes.md").read_text())

    def test_todos_with_due_dates_overdue_marks_and_completion(self) -> None:
        past = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
        self.tools["add_todo"].handler({"text": "Renew passport", "due": past})
        self.tools["add_todo"].handler({"text": "Buy paint"})
        listing = self.tools["list_todos"].handler({})
        self.assertIn(f"1. Renew passport (due {past}) [overdue]", listing)
        self.tools["complete_todo"].handler({"item": "paint"})
        self.assertIn("- [x] Buy paint", (self.docs / "To-do.md").read_text())
        self.assertNotIn("Buy paint", self.tools["list_todos"].handler({}))
        undo.undo_change({})
        self.assertIn("- [ ] Buy paint", (self.docs / "To-do.md").read_text())
        with self.assertRaisesRegex(ToolFailure, "'due'"):
            self.tools["add_todo"].handler({"text": "x", "due": "tomorrow"})

    def test_configured_files_are_used(self) -> None:
        store = Store({"personal": {"notes_file": str(self.docs / "mine" / "log.md")}})
        tools = {tool.name: tool for tool in note_tools(store.read)}
        tools["add_note"].handler({"text": "hello"})
        self.assertTrue((self.docs / "mine" / "log.md").exists())
        with self.assertRaisesRegex(SettingsError, "'notes_file' must be empty or an absolute path"):
            validate_settings({"personal": {"notes_file": "notes.md"}})


class MemoryTests(unittest.TestCase):
    def test_facts_go_into_the_visible_instructions_and_can_be_forgotten(self) -> None:
        store = Store({"agent": {"instructions": "Answer briefly."}})
        tools = {tool.name: tool for tool in memory_tools(store.read, store.update)}
        tools["remember"].handler({"fact": "My notes are in ~/Notes"})
        self.assertEqual(store.settings["agent"]["instructions"], "Answer briefly.\n- My notes are in ~/Notes")
        self.assertEqual(tools["remember"].handler({"fact": "my notes are in ~/notes"}), "That is already remembered.")
        self.assertEqual(tools["forget"].risk, RISK_DANGER)
        self.assertIn("Forgot 1", tools["forget"].handler({"about": "notes"}))
        self.assertEqual(tools["recall"].handler({}), "Answer briefly.")

    def test_the_length_limit_is_reported(self) -> None:
        store = Store({"agent": {"instructions": "x" * 3990}})
        tools = {tool.name: tool for tool in memory_tools(store.read, store.update)}
        with self.assertRaisesRegex(ToolFailure, "shorten their instructions"):
            tools["remember"].handler({"fact": "a fact that does not fit"})


if __name__ == "__main__":
    unittest.main()
