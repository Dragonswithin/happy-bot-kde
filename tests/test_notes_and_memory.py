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

from happy_bot.settings import SettingsError, validate_settings  # noqa: E402
from happy_bot.tools import undo  # noqa: E402
from happy_bot.tools.memory import memory_tools  # noqa: E402
from happy_bot.tools.notes import note_tools  # noqa: E402
from happy_bot.tools.registry import RISK_DANGER, ToolFailure  # noqa: E402


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
    def test_chat_facts_are_separate_from_instructions(self) -> None:
        store = Store({"agent": {"instructions": "Answer briefly."}})
        tools = {tool.name: tool for tool in memory_tools(store.read, store.update)}
        tools["remember"].handler({"fact": "My notes are in ~/Notes"})
        self.assertEqual(store.settings["agent"]["instructions"], "Answer briefly.")
        self.assertEqual(store.settings["agent"]["remembered_facts"], [{"text": "My notes are in ~/Notes", "local_only": True, "prompt": ""}])
        self.assertEqual(tools["remember"].handler({"fact": "my notes are in ~/notes"}), "That is already remembered.")
        self.assertEqual(tools["forget"].risk, RISK_DANGER)
        self.assertIn("Forgot 1", tools["forget"].handler({"about": "notes"}))
        self.assertEqual(tools["recall"].handler({}), "Nothing is remembered about the user yet.")

    def test_length_limit_is_independent_of_instructions(self) -> None:
        store = Store({"agent": {"instructions": "x" * 4000}})
        tools = {tool.name: tool for tool in memory_tools(store.read, store.update)}
        tools["remember"].handler({"fact": "fits even though instructions are full"})
        with self.assertRaisesRegex(ToolFailure, "500"):
            tools["remember"].handler({"fact": "y" * 501})

    def test_migration_edit_and_reload(self) -> None:
        from happy_bot.daemon_routes import edit_remembered_fact
        from happy_bot.settings import SUGGESTED_INSTRUCTIONS, save_settings, load_settings

        store = Store({"agent": {"instructions": SUGGESTED_INSTRUCTIONS + "\n- My notes are in ~/Notes"}})
        self.assertEqual(store.settings["agent"]["instructions"], SUGGESTED_INSTRUCTIONS)
        self.assertEqual(store.settings["agent"]["remembered_facts"], [{"text": "My notes are in ~/Notes", "local_only": True, "prompt": ""}])
        store.mutate_settings = store.update
        status, _ = edit_remembered_fact(
            store, {}, {"action": "edit", "old": "My notes are in ~/Notes", "fact": "My notes are in ~/Documents"}
        )
        self.assertEqual(status, 200)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(store.settings, path)
            again = load_settings(path)
            self.assertEqual(again["agent"]["remembered_facts"], [{"text": "My notes are in ~/Documents", "local_only": True, "prompt": ""}])
            self.assertEqual(again, validate_settings(again))

    def test_custom_bullets_move_only_when_selected(self) -> None:
        from happy_bot.daemon_routes import edit_remembered_fact

        store = Store({"agent": {"instructions": "- Answer briefly.\n- Use Kate."}})
        self.assertEqual(store.settings["agent"]["remembered_facts"], [])
        store.mutate_settings = store.update
        status, _ = edit_remembered_fact(store, {}, {"action": "move", "old": "- Use Kate."})
        self.assertEqual(status, 200)
        self.assertEqual(store.settings["agent"]["instructions"], "- Answer briefly.")
        self.assertEqual(store.settings["agent"]["remembered_facts"], [{"text": "Use Kate.", "local_only": True, "prompt": ""}])

    def test_open_chat_updates_and_privacy_apply_at_provider_boundary(self) -> None:
        from unittest.mock import patch
        from happy_bot.ask_stream import stream_ask
        from happy_bot.daemon_http import AssistantServer
        from happy_bot.daemon_routes import edit_remembered_fact
        from happy_bot.conversation import TextDelta, TurnEnd

        calls = []

        class Provider:
            def stream(self, messages, tools, cancel):
                calls.append((messages[0].text, [tool.name for tool in tools]))
                yield TextDelta("Done.")
                yield TurnEnd("stop", 1, 1)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            server = AssistantServer("127.0.0.1", 0, path / "runtime", path / "config.json", path / "history")
            try:
                server.replace_settings({"models": {
                    "local": {"provider": "openai_compatible", "base_url": "http://127.0.0.1:8000/v1", "model": "test"},
                    "hosted": {"provider": "openai_compatible", "base_url": "https://model.example/v1", "model": "test"},
                }, "agent": {"app_context": "local"}})
                chat = {tool.name: tool for tool in memory_tools(lambda: server.settings, server.mutate_settings)}
                chat["remember"].handler({"fact": "memory-original-value"})
                events = []
                with patch("happy_bot.ask_stream.create_provider", return_value=Provider()), \
                     patch("happy_bot.ask_stream.app_context.background_note", return_value=""), \
                     patch("happy_bot.ask_stream.sounds.play"):
                    stream_ask(server, {"message": "First request", "model": "local"}, events.append)
                    conversation = next(e["conversation_id"] for e in events if e["type"] == "start")
                    self.assertIn("memory-original-value", calls[-1][0])
                    status, _ = edit_remembered_fact(server, {}, {"action": "edit", "old": "memory-original-value",
                                                                 "fact": "memory-replacement-value"})
                    self.assertEqual(status, 200)
                    stream_ask(server, {"message": "Next", "conversation_id": conversation, "model": "local"}, events.append)
                    self.assertIn("memory-replacement-value", calls[-1][0])
                    self.assertNotIn("memory-original-value", calls[-1][0])
                    stream_ask(server, {"message": "Hosted", "conversation_id": conversation, "model": "hosted"}, events.append)
                    self.assertNotIn("memory-replacement-value", calls[-1][0])
                    self.assertNotIn("recall", calls[-1][1])
                    server.mutate_settings(lambda settings: settings["agent"].update(app_context="any"))
                    status, _ = edit_remembered_fact(server, {}, {
                        "action": "add", "fact": "Spanish", "prompt": "language", "local_only": False,
                    })
                    self.assertEqual(status, 200)
                    stream_ask(server, {"message": "Hosted with consent", "conversation_id": conversation,
                                        "model": "hosted"}, events.append)
                    self.assertIn("Preferred language: Spanish", calls[-1][0])
                    self.assertNotIn("memory-replacement-value", calls[-1][0])
                    status, _ = edit_remembered_fact(server, {}, {"action": "delete", "old": "memory-replacement-value"})
                    self.assertEqual(status, 200)
                    stream_ask(server, {"message": "After delete", "conversation_id": conversation, "model": "local"}, events.append)
                    self.assertNotIn("memory-replacement-value", calls[-1][0])
            finally:
                server.server_close()

    def test_model_payload_uses_live_facts_and_replaces_old_tool_transcripts(self) -> None:
        from happy_bot.ask_stream import _model_memory
        from happy_bot.conversation import Message, ToolCall

        history = [
            Message("system", "Normal instructions."),
            Message("assistant", tool_calls=(ToolCall("1", "remember", {"fact": "obsolete saved value"}),)),
            Message("tool", "obsolete saved value", tool_call_id="1", private=True),
        ]
        blocked = _model_memory(history, ["fresh saved value"], False)
        updated = _model_memory(history, ["fresh saved value"], True)
        deleted = _model_memory(history, [], True)
        self.assertNotIn("saved value", repr(blocked))
        self.assertIn("fresh saved value", updated[0].text)
        self.assertNotIn("obsolete saved value", repr(updated))
        self.assertNotIn("saved value", repr(deleted))
        self.assertIn("obsolete saved value", repr(history))


if __name__ == "__main__":
    unittest.main()
