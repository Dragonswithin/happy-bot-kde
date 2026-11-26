"""Tests for app_context (who may see what is read from the user's applications) and app_snapshot.

The privacy rules are the specification here: for each setting ("off", "local", "any") and each
kind of AI (on this computer or online), what the model's copy of the history holds. The desktop
readers are given fake windows, files and command output, so nothing on the machine is read.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401  (must come before the package: private runtime dir)

from happy_bot import app_context, app_snapshot  # noqa: E402
from happy_bot.conversation import Message, ToolCall  # noqa: E402
from happy_bot.redaction import HIDDEN  # noqa: E402

NOTE = "[Background: they had Kate open.]"
SECRET = "password = hunter22"


def history() -> list[Message]:
    call = ToolCall("c1", "ui_snapshot", {})
    return [
        Message("system", "You are the assistant."),
        Message("user", "how do I split this?", context=NOTE),
        Message("assistant", "", (call,)),
        Message("tool", f"Window controls: {SECRET}", tool_call_id="c1", private=True),
        Message("tool", f"config: {SECRET}", tool_call_id="c2"),
    ]


class ForModelTests(unittest.TestCase):
    def test_local_setting(self) -> None:
        local = app_context.for_model(history(), "local", local_model=True)
        self.assertEqual(local[1].text, f"{NOTE}\n\nhow do I split this?")
        self.assertIn(SECRET, local[3].text)  # nothing hidden from an AI on this computer
        online = app_context.for_model(history(), "local", local_model=False)
        self.assertEqual(online[1].text, "how do I split this?")
        self.assertEqual(online[3].text, app_context.WITHHELD)
        # A secret a local AI read before handing over is hidden from the online one.
        self.assertEqual(online[4].text, f"config: password = {HIDDEN}")

    def test_any_and_off_settings(self) -> None:
        online = app_context.for_model(history(), "any", local_model=False)
        self.assertTrue(online[1].text.startswith(NOTE))
        self.assertEqual(online[3].text, f"Window controls: password = {HIDDEN}")
        for local_model in (True, False):
            off = app_context.for_model(history(), "off", local_model=local_model)
            self.assertEqual(off[1].text, "how do I split this?")
        self.assertIn(SECRET, app_context.for_model(history(), "off", local_model=True)[3].text)
        self.assertEqual(app_context.for_model(history(), "off", local_model=False)[3].text, app_context.WITHHELD)

    def test_the_history_itself_is_unchanged_and_providers_get_plain_messages(self) -> None:
        original = history()
        prepared = app_context.for_model(original, "local", local_model=False)
        self.assertEqual(original, history())
        self.assertTrue(all(not message.context and not message.private for message in prepared))
        self.assertIs(prepared[0], original[0])


class ScreenshotTests(unittest.TestCase):
    def settings(self, policy: str, vision_local: bool, vision_online: bool) -> dict:
        return {"agent": {"app_context": policy, "local_only": False}, "model_order": ["npu", "claude"],
                "models": {"npu": {"base_url": "http://127.0.0.1:52625/v1", "vision": vision_local},
                           "claude": {"base_url": "https://api.anthropic.com/v1", "vision": vision_online}}}

    def test_a_screenshot_is_wanted_only_for_a_picture_ai_allowed_to_see_the_app(self) -> None:
        self.assertFalse(app_context.screenshots_wanted(self.settings("local", False, True)))
        self.assertTrue(app_context.screenshots_wanted(self.settings("local", True, False)))
        self.assertTrue(app_context.screenshots_wanted(self.settings("any", False, True)))
        self.assertFalse(app_context.screenshots_wanted(self.settings("off", True, True)))

    def test_clear_removes_only_generated_captures_and_forgets_pending_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            folder = runtime / "screenshots"
            folder.mkdir()
            window = folder / ("a" * 32 + ".png")
            desktop = folder / "desktop-context-1234.png"
            kept = folder / "chosen-picture.png"
            for file in (window, desktop, kept):
                file.touch()
            with mock.patch.object(app_snapshot, "capture_window", return_value=str(window)):
                app_context.remember_screenshot(self.settings("local", True, False), "window", runtime)
            app_context.clear_screenshots(runtime)
            app_context.clear_screenshots(runtime)
            self.assertEqual(list(folder.iterdir()), [kept])
            self.assertEqual(app_context.take_screenshot({"window": "window"}), "")

    def test_it_is_taken_on_request_and_used_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(app_snapshot, "capture_window", return_value=f"{tmp}/a.png") as capture:
            self.assertFalse(app_context.remember_screenshot(self.settings("local", False, False), "{w1}", Path(tmp)))
            capture.assert_not_called()
            self.assertTrue(app_context.remember_screenshot(self.settings("any", False, True), "{w1}", Path(tmp)))
        self.assertEqual(app_context.take_screenshot({"window": "{w1}"}), f"{tmp}/a.png")
        self.assertEqual(app_context.take_screenshot({"window": "{w1}"}), "")

    def test_pictures_reach_only_picture_ais_allowed_to_see_the_app(self) -> None:
        message = [Message("user", "what is this?", context=NOTE, images=("/tmp/a.png",))]
        self.assertEqual(app_context.for_model(message, "local", True, vision=True)[0].images, ("/tmp/a.png",))
        self.assertEqual(app_context.for_model(message, "local", True, vision=False)[0].images, ())
        self.assertEqual(app_context.for_model(message, "local", False, vision=True)[0].images, ())
        self.assertEqual(app_context.for_model(message, "any", False, vision=True)[0].images, ("/tmp/a.png",))


class BackgroundNoteTests(unittest.TestCase):
    def test_light_and_full_notes(self) -> None:
        window = {"id": "{w1}", "pid": 42, "app": "org.kde.kate", "title": "notes.txt — Kate"}
        about = {"app": "Kate", "class": "org.kde.kate", "title": "notes.txt — Kate", "window": "{w1}"}
        full = {"selection": "def split():", "controls": 'e1 button "Split View"', "document": "/home/u/notes.txt"}
        with mock.patch.object(app_context, "_window", return_value=window), \
                mock.patch.object(app_snapshot, "light_facts", return_value={"version": "24.12.3", "system": "Plasma 6.8 on Arch"}), \
                mock.patch.object(app_snapshot, "full_facts", return_value=full) as read_full:
            light = app_context.background_note(about)
            read_full.assert_not_called()
            heavy = app_context.background_note(about, full=True)
        self.assertIn('the application Kate 24.12.3 (window title: "notes.txt — Kate")', light)
        self.assertIn("on Plasma 6.8 on Arch", light)
        self.assertNotIn("Split View", light)
        for fact in full.values():
            self.assertIn(fact, heavy)
        self.assertEqual(app_context.background_note(None), "")
        self.assertEqual(app_context.background_note({"app": "", "title": ""}), "")


class SnapshotTests(unittest.TestCase):
    def test_help_window_capture_excludes_the_shadow_but_keeps_the_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(app_snapshot.shutil, "which", return_value="spectacle"), \
                mock.patch.object(app_snapshot, "_activate"), \
                mock.patch.object(app_snapshot, "_active_window_id", return_value="w"), \
                mock.patch.object(app_snapshot.time, "sleep"), \
                mock.patch.object(app_snapshot, "capture_png", return_value="window.png") as capture:
            self.assertEqual(app_context.preview_screenshot("w", False, Path(tmp)), "window.png")
            capture.assert_called_once_with(Path(tmp) / "screenshots", ["-a", "--no-shadow"])

    def test_the_open_document_comes_from_recent_files_named_in_the_title(self) -> None:
        xbel = """<?xml version="1.0"?>
<xbel version="1.0" xmlns:bookmark="http://www.freedesktop.org/standards/desktop-bookmarks">
 <bookmark href="file:///home/u/old%20notes.txt"><info><metadata><bookmark:applications>
  <bookmark:application name="org.kde.kate" exec="kate %u" modified="2026-01-01T00:00:00Z" count="1"/>
 </bookmark:applications></metadata></info></bookmark>
 <bookmark href="file:///home/u/notes.txt"><info><metadata><bookmark:applications>
  <bookmark:application name="org.kde.kate" exec="kate %u" modified="2026-02-01T00:00:00Z" count="1"/>
 </bookmark:applications></metadata></info></bookmark>
 <bookmark href="file:///home/u/other/notes.txt"><info><metadata><bookmark:applications>
  <bookmark:application name="org.kde.dolphin" exec="dolphin %u" modified="2026-03-01T00:00:00Z" count="1"/>
 </bookmark:applications></metadata></info></bookmark>
</xbel>"""
        with tempfile.TemporaryDirectory() as tmp:
            recent = Path(tmp, "recently-used.xbel")
            recent.write_text(xbel, encoding="utf-8")
            self.assertEqual(app_snapshot.open_document("org.kde.kate", "notes.txt — Kate", recent), "/home/u/notes.txt")
            self.assertEqual(app_snapshot.open_document("org.kde.kate", "old notes.txt — Kate", recent),
                             "/home/u/old notes.txt")
            self.assertEqual(app_snapshot.open_document("org.kde.kate", "Untitled — Kate", recent), "")
            self.assertEqual(app_snapshot.open_document("org.kde.kate", "x", Path(tmp, "missing.xbel")), "")

    def test_the_version_comes_from_the_owning_package(self) -> None:
        app_snapshot._package_version.cache_clear()
        answers = {"pacman": {"ok": True, "stdout": "/usr/bin/kate is owned by kate 24.12.3-1\n"}}
        with mock.patch.object(app_snapshot.shutil, "which", side_effect=lambda name: name == "pacman" or None), \
                mock.patch.object(app_snapshot, "run_command", side_effect=lambda command, timeout=5: answers[command[0]]):
            self.assertEqual(app_snapshot._package_version("/usr/bin/kate"), "24.12.3-1")
        app_snapshot._package_version.cache_clear()
        with mock.patch.object(app_snapshot.shutil, "which", return_value=None):
            self.assertEqual(app_snapshot._package_version("/usr/bin/kate"), "")
        app_snapshot._package_version.cache_clear()


if __name__ == "__main__":
    unittest.main()
