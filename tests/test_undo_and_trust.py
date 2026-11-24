"""Tests for undo, the activity record, the per-turn action list and secret redaction.

Covers ``undo_journal`` and ``tools/undo.py`` (file reversals run for real in
a temporary folder; desktop reversals run against a recorded fake of the
command runner), ``recent_activity`` over a written action log, the
``actions`` list ``agent_loop.run_turn`` puts on its ``done`` event, and
``redaction``. The runtime directory is redirected to a temporary one so the
user's real journal is never touched.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import undo_journal  # noqa: E402
from happy_bot.agent_loop import run_turn  # noqa: E402
from happy_bot.conversation import Message, TextDelta, ToolCall, ToolCallReady, TurnEnd  # noqa: E402
from happy_bot.redaction import HIDDEN, is_local_address, redact  # noqa: E402
from happy_bot.tools import files, undo  # noqa: E402
from happy_bot.tools.registry import (  # noqa: E402
    RISK_CHANGE, RISK_DANGER, RISK_READ, Tool, ToolFailure, ToolRegistry, object_schema)


class RuntimeDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root / "run")})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / "run").mkdir()
        self.work = self.root / "work"
        self.work.mkdir()


class FileUndoTests(RuntimeDirTest):
    def test_move_is_undone_and_a_second_undo_steps_further_back(self) -> None:
        first, second = self.work / "a.txt", self.work / "b.txt"
        first.write_text("hello")
        files.move_path({"source": str(first), "destination": str(second)})
        files.make_directory({"path": str(self.work / "new" / "deeper")})
        self.assertIn("Removed the folder", undo.undo_change({}))
        self.assertFalse((self.work / "new").exists())
        self.assertIn("Moved", undo.undo_change({}))
        self.assertEqual(first.read_text(), "hello")
        with self.assertRaisesRegex(ToolFailure, "nothing left to undo"):
            undo.undo_change({})

    def test_replaced_contents_come_back_and_appends_are_cut_off(self) -> None:
        target = self.work / "notes.txt"
        target.write_text("original")
        files.write_text_file({"path": str(target), "content": "new", "overwrite": True})
        self.assertEqual(undo.classify_undo({})[0], RISK_DANGER)
        undo.undo_change({})
        self.assertEqual(target.read_text(), "original")
        files.write_text_file({"path": str(target), "content": " more", "append": True})
        undo.undo_change({})
        self.assertEqual(target.read_text(), "original")

    def test_created_files_and_copies_go_to_the_trash(self) -> None:
        created = self.work / "created.txt"
        files.write_text_file({"path": str(created), "content": "x"})
        trashed = []
        with mock.patch.object(undo, "_trash", side_effect=lambda path: trashed.append(path) or "trashed"):
            self.assertIn("Undo: Created", undo.summarize_undo({}))
            undo.undo_change({})
        self.assertEqual(trashed, [str(created)])

    def test_a_folder_that_gained_content_is_left_alone(self) -> None:
        files.make_directory({"path": str(self.work / "box")})
        (self.work / "box" / "kept.txt").write_text("mine")
        with self.assertRaisesRegex(ToolFailure, "not empty"):
            undo.undo_change({})
        self.assertTrue((self.work / "box" / "kept.txt").exists())

    def test_move_back_refuses_when_the_old_place_is_taken(self) -> None:
        source, landing = self.work / "s.txt", self.work / "l.txt"
        source.write_text("1")
        files.move_path({"source": str(source), "destination": str(landing)})
        source.write_text("someone else")
        with self.assertRaisesRegex(ToolFailure, "something is now at"):
            undo.undo_change({})
        self.assertEqual(len(undo_journal.pending()), 1)  # still undoable later


class DesktopUndoTests(RuntimeDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.commands: list[list[str]] = []
        self.outputs: dict[str, str] = {}

        def fake_run(command, timeout=30.0):
            self.commands.append(command)
            return self.outputs.get(" ".join(command[:3]), "")

        patcher = mock.patch.object(undo, "_run", side_effect=fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_volume_scheme_setting_and_clipboard_are_set_back(self) -> None:
        undo_journal.record("clipboard", "Replaced the clipboard", {"text": "before"})
        undo_journal.record("kde_setting", "Set a key", {"file": "kdeglobals", "group": "G", "key": "K", "previous": None})
        undo_journal.record("color_scheme", "Changed scheme", {"scheme": "BreezeDark"})
        undo_journal.record("volume", "Changed volume", {"percent": 40, "mute": True})
        for _ in range(4):
            undo.undo_change({})
        self.assertEqual(self.commands[0][:3] + self.commands[0][3:], ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.40"])
        self.assertIn(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], self.commands)
        self.assertIn(["plasma-apply-colorscheme", "BreezeDark"], self.commands)
        self.assertIn("--delete", self.commands[3])
        self.assertEqual(self.commands[4][-1], "before")

    def test_trashed_item_is_restored_by_its_original_path(self) -> None:
        missing = str(self.work / "gone.txt")
        undo_journal.record("trashed", f"Moved {missing} to the trash", {"path": missing})
        self.outputs["gio trash --list"] = f"trash:///other\t/elsewhere\ntrash:///gone.txt\t{missing}\n"
        self.assertIn("Restored", undo.undo_change({}))
        self.assertEqual(self.commands[-1], ["gio", "trash", "--restore", "trash:///gone.txt"])

    def test_a_specific_change_can_be_undone_by_id(self) -> None:
        undo_journal.record("volume", "older", {"percent": 10, "mute": False})
        undo_journal.record("volume", "newer", {"percent": 90, "mute": False})
        older = undo_journal.pending()[1]["id"]
        undo.undo_change({"id": older})
        self.assertEqual([entry["summary"] for entry in undo_journal.pending()], ["newer"])
        with self.assertRaisesRegex(ToolFailure, "no change with id"):
            undo.undo_change({"id": older})


class ActivityTests(RuntimeDirTest):
    def test_activity_lists_the_action_log_and_what_can_be_undone(self) -> None:
        log = self.root / "run" / "happy-bot"
        log.mkdir()
        (log / "actions.jsonl").write_text("\n".join(json.dumps(record) for record in (
            {"time": "2026-11-22T10:00:00", "tool": "old_tool", "outcome": "ran without asking", "arguments": "{}"},
            {"time": "2026-11-23T09:00:00", "tool": "trash_path", "outcome": "deny", "arguments": "{\"path\": \"/x\"}"},
        )) + "\n")
        undo_journal.record("volume", "Changed the volume from 20%", {"percent": 20, "mute": False})
        text = undo.recent_activity({"since": "2026-11-23"})
        self.assertIn("trash_path  [deny]", text)
        self.assertNotIn("old_tool", text)
        self.assertIn("Changed the volume from 20%", text)
        with self.assertRaisesRegex(ToolFailure, "'limit'"):
            undo.recent_activity({"limit": 0})


class TurnActionsTests(unittest.TestCase):
    class Gate:
        def check(self, call_id, tool, arguments, risk, summary, detail):
            return (False, "The user declined.") if tool == "risky" else (True, "")

    class Provider:
        def __init__(self, *replies):
            self.replies = list(replies)
            self.seen = []

        def stream(self, messages, tools, cancel):
            self.seen.append(list(messages))
            yield from self.replies.pop(0)
            yield TurnEnd("stop")

    def test_done_event_says_what_was_done_failed_and_declined(self) -> None:
        def fail(arguments):
            raise ToolFailure("no")

        registry = ToolRegistry([
            Tool("look", "Read.", object_schema(), RISK_READ, lambda a: "seen"),
            Tool("change", "Change.", object_schema(), RISK_CHANGE, lambda a: "changed", summarize=lambda a: "Change it"),
            Tool("broken", "Fails.", object_schema(), RISK_CHANGE, fail, summarize=lambda a: "Try it"),
            Tool("risky", "Danger.", object_schema(), RISK_DANGER, lambda a: "x", summarize=lambda a: "Delete it"),
        ])
        calls = [ToolCallReady(ToolCall(str(index), name, {})) for index, name in enumerate(["look", "change", "broken", "risky"])]
        events = []
        run_turn(self.Provider(calls, [TextDelta("Done everything!")]), [Message("user", "go")], registry,
                 events.append, threading.Event(), gate=self.Gate())
        self.assertEqual(events[-1]["actions"], [
            {"summary": "Change it", "outcome": "done"},
            {"summary": "Try it", "outcome": "failed"},
            {"summary": "Delete it", "outcome": "declined"},
        ])

    def test_hosted_models_get_redacted_tool_results(self) -> None:
        registry = ToolRegistry([Tool("read", "Read.", object_schema(), RISK_READ, lambda a: "password=hunter22")])
        for redacting, expected in ((True, f"password={HIDDEN}"), (False, "password=hunter22")):
            provider = self.Provider([ToolCallReady(ToolCall("1", "read", {}))], [TextDelta("ok")])
            events = []
            run_turn(provider, [Message("user", "go")], registry, events.append, threading.Event(), redact=redacting)
            with self.subTest(redacting=redacting):
                self.assertEqual(provider.seen[1][-1].text, expected)
                self.assertEqual(next(e for e in events if e["type"] == "tool_result")["text"], expected)


class RedactionTests(unittest.TestCase):
    def test_known_secret_shapes_are_hidden_and_names_kept(self) -> None:
        cases = {
            "export OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456": "OPENAI_API_KEY=" + HIDDEN,
            'token: "ghp_abcdefghijklmnopqrstuvwxyz0123456789"': "token: \"" + HIDDEN,
            '{"client_secret": "s3cr3t-value"}': '{"client_secret": "' + HIDDEN + '"}',
            "Authorization: Bearer abc.def.ghi": "Authorization: Bearer " + HIDDEN,
            "aws AKIAABCDEFGHIJKLMNOP here": "aws " + HIDDEN + " here",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----": HIDDEN,
            "password = hunter22": "password = " + HIDDEN,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIn(expected, redact(text))
                self.assertNotIn("hunter22", redact(text))

    def test_ordinary_text_is_untouched(self) -> None:
        for text in ("The token count is 5", "Password reset instructions are in the wiki", "skeleton key", "/home/u/Documents"):
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)

    def test_local_addresses(self) -> None:
        self.assertTrue(is_local_address("http://127.0.0.1:52626/v1"))
        self.assertTrue(is_local_address("http://localhost:11434/v1"))
        self.assertTrue(is_local_address("http://[::1]:8080/v1"))
        self.assertFalse(is_local_address("https://api.example.com/v1"))
        self.assertFalse(is_local_address("http://192.168.1.5:8080/v1"))


if __name__ == "__main__":
    unittest.main()
